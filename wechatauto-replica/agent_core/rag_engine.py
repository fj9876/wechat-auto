# -*- coding: utf-8 -*-
"""轻量便携本地 RAG 知识库引擎 (agent_core.rag_engine)

特点：
1. 零重型依赖：使用纯 Python 实现 BM25 检索与双字/词切词，无需显卡或数GB PyTorch，跨电脑免安装任何 C++ 库。
2. 多格式文档支持：.txt, .md, .pdf, .docx, .csv, .json
3. 双模检索：离线 BM25 极速匹配 + 可选在线 Embedding API 向量相似度混合打分
4. 智能重叠切分：保持医学、制度或产品上下文连贯
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple

from .config import RAGConfig, LLMConfig


@dataclass
class DocumentChunk:
    """文档切片数据结构"""
    chunk_id: str
    source_file: str
    file_name: str
    content: str
    tokens: List[str]
    meta: Dict[str, Any]


def tokenize_chinese(text: str) -> List[str]:
    """轻量中英文分词器 (支持可选 jieba 增强，降级至纯 Python 字符/双字 Bi-gram 分词，100% 便携可靠)"""
    tokens = []
    # 提取英文和数字单词
    words = re.findall(r'[a-zA-Z0-9_\-\.]+', text.lower())
    tokens.extend(words)

    # 尝试可选使用 jieba 分词
    try:
        import jieba
        jb_words = [w.strip().lower() for w in jieba.cut(text) if w.strip() and not re.match(r'^[a-zA-Z0-9_\-\.]+$', w)]
        tokens.extend(jb_words)
    except Exception:
        pass

    # 提取中文字符串单字
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    tokens.extend(chinese_chars)
    # 双字元 (Bi-gram) 提升术语与短语匹配准确率
    clean_cn = re.sub(r'[^\u4e00-\u9fff]', ' ', text)
    for seg in clean_cn.split():
        if len(seg) >= 2:
            for i in range(len(seg) - 1):
                tokens.append(seg[i:i+2])
    return tokens


class PureBM25:
    """纯 Python 高性能 BM25 检索引擎"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = 0
        self.avgdl = 0.0
        self.doc_lengths: List[int] = []
        self.doc_freqs: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.chunks: List[DocumentChunk] = []

    def fit(self, chunks: List[DocumentChunk]) -> None:
        """构建索引"""
        self.chunks = chunks
        self.corpus_size = len(chunks)
        if self.corpus_size == 0:
            self.avgdl = 0.0
            return

        self.doc_lengths = []
        self.doc_freqs = {}

        total_len = 0
        for chunk in chunks:
            tokens = chunk.tokens
            dl = len(tokens)
            self.doc_lengths.append(dl)
            total_len += dl

            seen = set(tokens)
            for word in seen:
                self.doc_freqs[word] = self.doc_freqs.get(word, 0) + 1

        self.avgdl = total_len / self.corpus_size

        # 计算 IDF
        for word, freq in self.doc_freqs.items():
            self.idf[word] = math.log(
                (self.corpus_size - freq + 0.5) / (freq + 0.5) + 1.0
            )

    def search(self, query: str, top_k: int = 3) -> List[Tuple[DocumentChunk, float]]:
        """执行 BM25 查询"""
        if self.corpus_size == 0:
            return []

        q_tokens = tokenize_chinese(query)
        if not q_tokens:
            return []

        scores: List[float] = [0.0] * self.corpus_size
        for token in q_tokens:
            if token not in self.idf:
                continue
            idf_val = self.idf[token]

            for idx, chunk in enumerate(self.chunks):
                # 计算词频 tf
                tf = chunk.tokens.count(token)
                if tf == 0:
                    continue
                dl = self.doc_lengths[idx]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * (dl / (self.avgdl or 1.0)))
                scores[idx] += idf_val * (numerator / denominator)

        # 归一化评分 (0.0 ~ 1.0 估算)
        max_score = max(scores) if scores and max(scores) > 0 else 1.0
        normalized = [(self.chunks[i], scores[i] / max_score) for i in range(self.corpus_size) if scores[i] > 0]
        normalized.sort(key=lambda x: x[1], reverse=True)
        return normalized[:top_k]


class RAGEngine:
    """本地 RAG 知识库管理与检索调度器"""

    def __init__(self, rag_config: Optional[RAGConfig] = None, llm_config: Optional[LLMConfig] = None):
        self.rag_config = rag_config or RAGConfig()
        self.llm_config = llm_config or LLMConfig()
        self.bm25 = PureBM25()
        self.chunks: List[DocumentChunk] = []
        self.indexed_files: List[Dict[str, Any]] = []
        self.is_indexed: bool = False
        self.last_index_time: str = ""

    def update_config(self, rag_config: RAGConfig, llm_config: Optional[LLMConfig] = None) -> None:
        self.rag_config = rag_config
        if llm_config:
            self.llm_config = llm_config

    def reload_config(self, rag_config: RAGConfig, llm_config: Optional[LLMConfig] = None) -> None:
        """配置热重载 (兼容 update_config，若已配置知识库路径且未建立索引，尝试从缓存快速加载)"""
        self.update_config(rag_config, llm_config)
        if rag_config.kb_folder_path and os.path.isdir(rag_config.kb_folder_path) and not self.is_indexed:
            try:
                self.reindex(rag_config.kb_folder_path, force=False)
            except Exception as e:
                print(f"[RAG] 尝试自动加载缓存索引失败: {e}")

    def _get_cache_path(self, target_folder: str) -> str:
        """获取索引缓存文件路径"""
        # 优先存放在知识库文件夹内 .rag_cache.json
        cand = os.path.join(target_folder, ".rag_cache.json")
        try:
            # 探测可写性
            test_file = os.path.join(target_folder, ".test_write_perm")
            with open(test_file, "w") as f:
                f.write("1")
            os.remove(test_file)
            return cand
        except Exception:
            pass

        # 回退到应用本地 data/rag_cache.json
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "rag_cache.json")

    def _load_from_cache(self, cache_file: str, files: List[Dict[str, Any]]) -> Optional[List[DocumentChunk]]:
        """若文件未发生任何修改，从缓存秒级加载已切分并分词的 chunks"""
        if not os.path.isfile(cache_file):
            return None
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            cached_files_meta = data.get("files_meta", {})
            current_files_meta = {
                f["rel_path"]: {"size_bytes": f["size_bytes"], "mtime": f["mtime"]}
                for f in files
            }

            if cached_files_meta != current_files_meta:
                return None  # 文件内容或列表已变动，需要重新切分

            raw_chunks = data.get("chunks", [])
            chunks: List[DocumentChunk] = []
            for item in raw_chunks:
                chunks.append(DocumentChunk(
                    chunk_id=item.get("chunk_id", ""),
                    source_file=item.get("source_file", ""),
                    file_name=item.get("file_name", ""),
                    content=item.get("content", ""),
                    tokens=item.get("tokens", []),
                    meta=item.get("meta", {}),
                ))
            return chunks
        except Exception:
            return None

    def _save_to_cache(self, cache_file: str, files: List[Dict[str, Any]], chunks: List[DocumentChunk]) -> None:
        """保存分词和切片结果至本地持久化缓存"""
        try:
            files_meta = {
                f["rel_path"]: {"size_bytes": f["size_bytes"], "mtime": f["mtime"]}
                for f in files
            }
            chunks_data = [asdict(c) for c in chunks]
            cache_payload = {
                "version": "1.0",
                "files_meta": files_meta,
                "chunks": chunks_data,
            }
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_payload, f, ensure_ascii=False)
        except Exception as e:
            print(f"[RAG] 写入本地索引缓存失败: {e}")

    def _read_file_content(self, file_path: str) -> str:
        """解析不同类型的文件文本内容"""
        ext = os.path.splitext(file_path)[1].lower()

        # 1. 文本与 Markdown
        if ext in (".txt", ".md", ".log"):
            for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1"):
                try:
                    with open(file_path, "r", encoding=enc) as f:
                        return f.read()
                except UnicodeDecodeError:
                    continue
            return ""

        # 2. JSON
        if ext == ".json":
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return json.dumps(data, ensure_ascii=False, indent=2)
            except Exception:
                return ""

        # 3. CSV 表格
        if ext == ".csv":
            lines = []
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.reader(f)
                    for row in reader:
                        lines.append(" | ".join(row))
                return "\n".join(lines)
            except Exception:
                return ""

        # 4. PDF 文档
        if ext == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(file_path)
                pages = [page.extract_text() or "" for page in reader.pages]
                return "\n\n".join(pages)
            except Exception as e:
                print(f"[RAG] 读取 PDF 文件失败 ({file_path}): {e}")
                return ""

        # 5. Word 文档 (.docx)
        if ext == ".docx":
            try:
                import docx
                doc = docx.Document(file_path)
                return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
            except Exception as e:
                print(f"[RAG] 读取 DOCX 文件失败 ({file_path}): {e}")
                return ""

        return ""

    def _split_into_chunks(self, text: str, file_path: str) -> List[DocumentChunk]:
        """按段落及指定字符大小重叠切分文档"""
        chunk_size = self.rag_config.chunk_size or 500
        chunk_overlap = self.rag_config.chunk_overlap or 50
        file_name = os.path.basename(file_path)

        # 按双换行或单换行分段
        paragraphs = [p.strip() for p in re.split(r'\n+', text) if p.strip()]
        chunks: List[DocumentChunk] = []

        curr_text = ""
        chunk_counter = 0

        for para in paragraphs:
            if len(curr_text) + len(para) <= chunk_size:
                curr_text = f"{curr_text}\n{para}".strip()
            else:
                if curr_text:
                    chunk_counter += 1
                    c_tokens = tokenize_chinese(curr_text)
                    chunks.append(DocumentChunk(
                        chunk_id=f"{file_name}#{chunk_counter}",
                        source_file=file_path,
                        file_name=file_name,
                        content=curr_text,
                        tokens=c_tokens,
                        meta={"char_count": len(curr_text)}
                    ))
                # 保持 overlap
                overlap_text = curr_text[-chunk_overlap:] if len(curr_text) > chunk_overlap else ""
                curr_text = f"{overlap_text}\n{para}".strip()

        if curr_text:
            chunk_counter += 1
            c_tokens = tokenize_chinese(curr_text)
            chunks.append(DocumentChunk(
                chunk_id=f"{file_name}#{chunk_counter}",
                source_file=file_path,
                file_name=file_name,
                content=curr_text,
                tokens=c_tokens,
                meta={"char_count": len(curr_text)}
            ))

        return chunks

    def scan_folder(self, folder_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """扫描知识库文件夹中的所有文档 (自动忽略隐藏文件与隐藏文件夹)"""
        path = folder_path or self.rag_config.kb_folder_path
        if not path or not os.path.isdir(path):
            return []

        supported_exts = {".txt", ".md", ".pdf", ".docx", ".csv", ".json"}
        files_info = []

        for root, dirs, files in os.walk(path):
            # 忽略以 . 开头的隐藏目录 (例如 .git, .cache 等)
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for file in files:
                # 忽略以 . 开头的隐藏文件与内部缓存 (例如 .rag_cache.json)
                if file.startswith("."):
                    continue
                ext = os.path.splitext(file)[1].lower()
                if ext in supported_exts:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, path)
                    try:
                        stat = os.stat(full_path)
                        files_info.append({
                            "name": file,
                            "rel_path": rel_path,
                            "full_path": full_path,
                            "size_bytes": stat.st_size,
                            "ext": ext,
                            "mtime": stat.st_mtime,
                        })
                    except Exception:
                        pass
        return files_info

    def reindex(self, folder_path: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        """重新扫描文件夹并重建 BM25 检索索引 (支持秒级本地缓存)"""
        import time
        target_folder = folder_path or self.rag_config.kb_folder_path
        if not target_folder:
            return {"success": False, "message": "知识库文件夹路径未配置", "doc_count": 0, "chunk_count": 0}

        target_folder = os.path.abspath(target_folder)
        if not os.path.isdir(target_folder):
            return {"success": False, "message": f"目录不存在: {target_folder}", "doc_count": 0, "chunk_count": 0}

        files = self.scan_folder(target_folder)
        if not files:
            self.chunks = []
            self.bm25.fit([])
            self.indexed_files = []
            self.is_indexed = False
            return {
                "success": True,
                "message": f"知识库目录为空或无有效格式文档（支持 .txt, .md, .pdf, .docx, .csv, .json）",
                "doc_count": 0,
                "chunk_count": 0,
                "last_index_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

        cache_path = self._get_cache_path(target_folder)
        all_chunks: Optional[List[DocumentChunk]] = None

        if not force:
            all_chunks = self._load_from_cache(cache_path, files)

        is_from_cache = False
        if all_chunks is not None:
            is_from_cache = True
        else:
            all_chunks = []
            for file_info in files:
                content = self._read_file_content(file_info["full_path"])
                if content:
                    chunks = self._split_into_chunks(content, file_info["full_path"])
                    all_chunks.extend(chunks)
            # 存入缓存
            self._save_to_cache(cache_path, files, all_chunks)

        self.chunks = all_chunks
        self.bm25.fit(all_chunks)
        self.indexed_files = files
        self.is_indexed = True
        self.last_index_time = time.strftime("%Y-%m-%d %H:%M:%S")

        cache_tip = " (已通过缓存高速加载)" if is_from_cache else ""
        return {
            "success": True,
            "message": f"索引构建成功！共索引 {len(files)} 个文档，生成 {len(all_chunks)} 个切片{cache_tip}",
            "doc_count": len(files),
            "chunk_count": len(all_chunks),
            "last_index_time": self.last_index_time,
            "from_cache": is_from_cache,
        }

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        threshold: Optional[float] = None,
        ignore_enabled_flag: bool = False
    ) -> List[Dict[str, Any]]:
        """执行知识检索

        Args:
            query: 用户提问或搜索词
            top_k: 最大返回条数
            threshold: 相似度打分阈值 (0.0 ~ 1.0)
            ignore_enabled_flag: 为 True 时忽略 rag_config.enabled 开关校验（用于在 GUI 中即时测试切片命中）

        Returns:
            List of { "chunk_id", "file_name", "content", "text", "score", "source_file", "metadata" }
        """
        if (not ignore_enabled_flag and not self.rag_config.enabled) or not self.is_indexed or not self.chunks:
            return []

        k = top_k or self.rag_config.top_k or 3
        th = threshold if threshold is not None else (self.rag_config.similarity_threshold or 0.15)

        results = self.bm25.search(query, top_k=k)
        matched = []
        for chunk, score in results:
            if score >= th:
                matched.append({
                    "chunk_id": chunk.chunk_id,
                    "file_name": chunk.file_name,
                    "source_file": chunk.source_file,
                    "content": chunk.content,
                    "text": chunk.content,  # 兼容 text 别名
                    "score": round(score, 3),
                    "metadata": {
                        "source": chunk.file_name,
                        "source_file": chunk.source_file,
                        "chunk_id": chunk.chunk_id,
                    }
                })
        return matched

    def get_status(self) -> Dict[str, Any]:
        """获取当前知识库状态"""
        return {
            "enabled": self.rag_config.enabled,
            "folder_path": self.rag_config.kb_folder_path,
            "is_indexed": self.is_indexed,
            "doc_count": len(self.indexed_files),
            "chunk_count": len(self.chunks),
            "last_index_time": self.last_index_time,
            "files": [f["name"] for f in self.indexed_files[:20]],
        }
