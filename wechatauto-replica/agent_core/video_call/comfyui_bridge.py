# -*- coding: utf-8 -*-
"""ComfyUI 本地接口桥接器 (agent_core.video_call.comfyui_bridge)

负责与本地运行的 ComfyUI 实例 (默认 http://127.0.0.1:8188) 通信：
1. 连通性与服务状态自检
2. 历史生成图片查询与一键导入为数字人正面立绘
3. 触发工作流执行与图片拉取
"""
from __future__ import annotations

import os
import time
import json
import logging
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional, Dict, Any, List

logger = logging.getLogger("ComfyUIBridge")


class ComfyUIBridge:
    """ComfyUI API 桥接器"""

    def __init__(self, base_url: str = "http://127.0.0.1:8188"):
        self.base_url = base_url.rstrip("/")

    def set_base_url(self, url: str):
        """设置 ComfyUI 服务地址"""
        self.base_url = url.rstrip("/")

    def check_connection(self) -> bool:
        """快速检测本地 ComfyUI 服务是否处于运行状态"""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/system_stats",
                headers={"User-Agent": "WeChat-AIAgent/1.0"}
            )
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def get_system_stats(self) -> Dict[str, Any]:
        """获取 ComfyUI 系统与显存占用状态"""
        try:
            req = urllib.request.Request(f"{self.base_url}/system_stats")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.debug(f"[ComfyUIBridge] 获取系统信息异常: {e}")
        return {}

    def fetch_latest_output_image(self, target_save_dir: str = "data/avatars") -> Optional[str]:
        """从 ComfyUI 最近的历史生成记录中拉取最新生成的图像并保存到指定目录"""
        try:
            req = urllib.request.Request(f"{self.base_url}/history?max_items=5")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status != 200:
                    return None
                history_data = json.loads(resp.read().decode("utf-8"))

            if not history_data:
                logger.info("[ComfyUIBridge] ComfyUI 无近期生成历史")
                return None

            # 遍历寻找最近的输出图片
            latest_image_meta = None
            latest_prompt_id = None
            sorted_history = sorted(
                history_data.items(),
                key=lambda item: item[1].get("prompt", [0])[0] if isinstance(item[1].get("prompt"), list) else 0,
                reverse=True
            )

            for prompt_id, p_info in sorted_history:
                outputs = p_info.get("outputs", {})
                for node_id, node_out in outputs.items():
                    images = node_out.get("images", [])
                    if images:
                        latest_image_meta = images[-1]
                        latest_prompt_id = prompt_id
                        break
                if latest_image_meta:
                    break

            if not latest_image_meta:
                logger.warning("[ComfyUIBridge] 未在历史记录中找到生成的图片节点输出")
                return None

            filename = latest_image_meta.get("filename")
            subfolder = latest_image_meta.get("subfolder", "")
            img_type = latest_image_meta.get("type", "output")

            # 构造获取图片参数
            params = urllib.parse.urlencode({
                "filename": filename,
                "subfolder": subfolder,
                "type": img_type
            })
            view_url = f"{self.base_url}/view?{params}"

            os.makedirs(target_save_dir, exist_ok=True)
            timestamp = int(time.time())
            save_name = f"comfyui_avatar_{timestamp}.png"
            dest_path = os.path.join(target_save_dir, save_name)

            img_req = urllib.request.Request(view_url)
            with urllib.request.urlopen(img_req, timeout=10.0) as img_resp:
                img_data = img_resp.read()
                with open(dest_path, "wb") as f:
                    f.write(img_data)

            logger.info(f"[ComfyUIBridge] 成功从 ComfyUI 导入最新生成立绘: {dest_path}")
            return dest_path

        except Exception as e:
            logger.error(f"[ComfyUIBridge] 拉取 ComfyUI 图像失败: {e}", exc_info=True)
            return None
