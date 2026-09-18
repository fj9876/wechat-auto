# -*- coding: utf-8 -*-
"""WeChat-AIAgent 配置与用户画像备份管理引擎 (agent_core.config_manager)

提供全量配置与联系人画像数据的打包导出、元数据校验、账号强一致性核验与解包恢复。
"""
from __future__ import annotations

import os
import json
import time
import zipfile
import shutil
from typing import Dict, Any, Tuple, Optional, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DEFAULT_PROFILES_DIR = os.path.join(BASE_DIR, "data", "profiles")


class ImportResult(dict):
    """支持字典解构与 (success, message) 二元组解包的导入结果包装类"""

    @property
    def success(self) -> bool:
        return bool(self.get("success", False))

    @property
    def message(self) -> str:
        if self.get("success"):
            p_count = self.get("restored_profiles_count", 0)
            return f"成功恢复配置与 {p_count} 个联系人画像"
        return str(self.get("error") or "导入失败")

    def __iter__(self):
        yield self.success
        yield self.message


class ConfigManager:
    """全量配置与记忆画像备份管理器"""

    BACKUP_VERSION = "2.0"
    METADATA_FILENAME = "metadata.json"
    CONFIG_FILENAME = "config.json"
    PROFILES_DIR_NAME = "profiles"

    @classmethod
    def export_backup_package(
        cls,
        output_zip_path: Optional[str] = None,
        current_wxid: str = "",
        current_name: str = "",
        config_path: Optional[str] = None,
        profiles_dir: Optional[str] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """将当前全量配置与联系人画像打包导出为 ZIP 文件

        Args:
            output_zip_path: 目标 ZIP 文件路径 (支持别名 out_path)
            current_wxid: 当前微信唯一标识符 (支持别名 self_wxid)
            current_name: 当前微信昵称 (支持别名 self_name)
            config_path: config.json 实际物理路径 (缺省使用项目默认路径)
            profiles_dir: data/profiles 实际物理路径 (缺省使用项目默认路径)
            extra_meta: 附加元数据

        Returns:
            导出的统计摘要字典
        """
        zip_path = output_zip_path or kwargs.get("out_path") or ""
        if not zip_path:
            raise ValueError("output_zip_path 路径不能为空")

        wxid = current_wxid or kwargs.get("self_wxid") or ""
        name = current_name or kwargs.get("self_name") or ""
        cfg_path = config_path or kwargs.get("config_file") or DEFAULT_CONFIG_PATH
        prof_dir = profiles_dir or kwargs.get("profiles_path") or DEFAULT_PROFILES_DIR

        output_dir = os.path.dirname(os.path.abspath(zip_path))
        os.makedirs(output_dir, exist_ok=True)

        # 统计画像文件
        profile_files: List[str] = []
        if os.path.isdir(prof_dir):
            for fname in os.listdir(prof_dir):
                if fname.endswith(".json"):
                    full_p = os.path.join(prof_dir, fname)
                    if os.path.isfile(full_p):
                        profile_files.append(full_p)

        # 构造元数据清单
        metadata: Dict[str, Any] = {
            "success": True,
            "app": "WeChat-AIAgent",
            "backup_version": cls.BACKUP_VERSION,
            "export_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": time.time(),
            "self_wxid": (wxid or "").strip(),
            "self_name": (name or "").strip(),
            "has_config": os.path.isfile(cfg_path),
            "profiles_count": len(profile_files),
        }
        if extra_meta:
            metadata.update(extra_meta)

        # 写入 ZIP 文件
        temp_zip = zip_path + ".tmp"
        try:
            with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                # 1. 写入元数据清单
                zf.writestr(
                    cls.METADATA_FILENAME,
                    json.dumps(metadata, ensure_ascii=False, indent=2)
                )

                # 2. 写入全局配置文件 config.json
                if os.path.isfile(cfg_path):
                    with open(cfg_path, "rb") as cf:
                        zf.writestr(cls.CONFIG_FILENAME, cf.read())

                # 3. 写入所有专属画像 JSON 文件
                for pf in profile_files:
                    arcname = f"{cls.PROFILES_DIR_NAME}/{os.path.basename(pf)}"
                    with open(pf, "rb") as pff:
                        zf.writestr(arcname, pff.read())

            if os.path.exists(zip_path):
                os.remove(zip_path)
            shutil.move(temp_zip, zip_path)
        finally:
            if os.path.exists(temp_zip):
                try:
                    os.remove(temp_zip)
                except Exception:
                    pass

        return metadata

    @classmethod
    def inspect_backup_package(cls, zip_path: str) -> Dict[str, Any]:
        """读取并检查备份包元数据，不解压

        Args:
            zip_path: 备份 ZIP 文件路径

        Returns:
            元数据字典
        """
        if not os.path.isfile(zip_path):
            raise FileNotFoundError(f"备份文件不存在: {zip_path}")

        if not zipfile.is_zipfile(zip_path):
            raise ValueError("所选文件不是有效的 ZIP 压缩包")

        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()
            if cls.METADATA_FILENAME not in namelist:
                raise ValueError("备份包缺少 metadata.json 元数据清单，可能非本系统导出文件")

            raw_meta = zf.read(cls.METADATA_FILENAME).decode("utf-8")
            metadata = json.loads(raw_meta)

            if cls.CONFIG_FILENAME not in namelist:
                metadata["warning_missing_config"] = True

            profiles = [f for f in namelist if f.startswith(f"{cls.PROFILES_DIR_NAME}/") and f.endswith(".json")]
            metadata["actual_profiles_in_archive"] = len(profiles)

            return metadata

    @classmethod
    def validate_account_match(
        cls,
        zip_path: Optional[str] = None,
        current_logged_in_wxid: str = "",
        current_logged_in_name: str = "",
        wechat_detected: bool = True,
        **kwargs
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """强校验当前登录的微信账号与备份中的账号是否一致

        Args:
            zip_path: 待导入的备份文件路径 (支持别名 backup_path)
            current_logged_in_wxid: 当前客户端检测到的已登录微信号 (支持别名 current_wxid)
            current_logged_in_name: 当前客户端检测到的已登录昵称 (支持别名 current_name)
            wechat_detected: 是否检测到微信运行

        Returns:
            (is_valid: bool, message: str, metadata: dict)
        """
        backup_p = zip_path or kwargs.get("backup_path") or ""
        curr_wxid = current_logged_in_wxid or kwargs.get("current_wxid") or ""
        curr_name = current_logged_in_name or kwargs.get("current_name") or ""
        is_detected = kwargs.get("wechat_detected", wechat_detected)

        try:
            metadata = cls.inspect_backup_package(backup_p)
        except Exception as e:
            return False, f"读取备份文件失败: {e}", {}

        target_wxid = (metadata.get("self_wxid") or "").strip()
        target_name = (metadata.get("self_name") or "").strip()
        current_wxid_clean = (curr_wxid or "").strip()
        current_name_clean = (curr_name or "").strip()

        # 1. 如果当前微信未登录或未连接
        if not is_detected or not current_wxid_clean:
            msg = (
                "【安全拦截】未检测到当前电脑登录的微信账号！\n\n"
                f"此备份归属于账号：{target_name or '未知'} ({target_wxid or '未绑定'})\n\n"
                "为防止配置与好友记忆错乱，导入前必须确保微信已在电脑登录并完成连接。"
            )
            return False, msg, metadata

        # 2. 如果备份包有绑定微信号，且与当前登录账号不匹配
        if target_wxid and current_wxid_clean.lower() != target_wxid.lower():
            msg = (
                "【账号不匹配 · 禁止导入】\n\n"
                f"• 备份归属账号: {target_name or '未知'} ({target_wxid})\n"
                f"• 当前登录账号: {current_name_clean or '未知'} ({current_wxid_clean})\n\n"
                "安全规则限制：不同微信账号之间严禁互相导入配置与用户画像记忆，"
                "以防止好友名单串号与私人记忆泄露。"
            )
            return False, msg, metadata

        # 3. 校验通过
        success_msg = f"微信账号核验一致: {current_name_clean or target_name} ({current_wxid_clean})"
        return True, success_msg, metadata

    @classmethod
    def import_backup_package(
        cls,
        zip_path: Optional[str] = None,
        target_config_path: Optional[str] = None,
        target_profiles_dir: Optional[str] = None,
        **kwargs
    ) -> ImportResult:
        """安全解包并恢复配置与用户画像

        Args:
            zip_path: 备份 ZIP 文件路径 (支持别名 backup_path)
            target_config_path: 恢复到的 config.json 目标路径 (缺省使用项目默认路径)
            target_profiles_dir: 恢复到的 data/profiles 目标路径 (缺省使用项目默认路径)

        Returns:
            导入结果对象 (支持字典解构与 (ok, msg) 解包)
        """
        backup_p = zip_path or kwargs.get("backup_path") or ""
        if not backup_p:
            return ImportResult({"success": False, "error": "未提供备份文件路径"})

        target_cfg = target_config_path or kwargs.get("config_path") or DEFAULT_CONFIG_PATH
        target_prof = target_profiles_dir or kwargs.get("profiles_dir") or DEFAULT_PROFILES_DIR

        try:
            metadata = cls.inspect_backup_package(backup_p)

            os.makedirs(os.path.dirname(os.path.abspath(target_cfg)), exist_ok=True)
            os.makedirs(target_prof, exist_ok=True)

            restored_profiles = 0
            has_restored_config = False

            with zipfile.ZipFile(backup_p, "r") as zf:
                for item in zf.infolist():
                    # 还原 config.json
                    if item.filename == cls.CONFIG_FILENAME:
                        content = zf.read(item.filename)
                        json.loads(content.decode("utf-8"))
                        with open(target_cfg, "wb") as f:
                            f.write(content)
                        has_restored_config = True

                    # 还原 profiles/*.json
                    elif item.filename.startswith(f"{cls.PROFILES_DIR_NAME}/") and item.filename.endswith(".json"):
                        fname = os.path.basename(item.filename)
                        if fname:
                            content = zf.read(item.filename)
                            json.loads(content.decode("utf-8"))
                            out_p = os.path.join(target_prof, fname)
                            with open(out_p, "wb") as f:
                                f.write(content)
                            restored_profiles += 1

            return ImportResult({
                "success": True,
                "restored_config": has_restored_config,
                "restored_profiles_count": restored_profiles,
                "metadata": metadata,
            })
        except Exception as e:
            return ImportResult({
                "success": False,
                "error": str(e),
                "restored_config": False,
                "restored_profiles_count": 0,
                "metadata": {},
            })
