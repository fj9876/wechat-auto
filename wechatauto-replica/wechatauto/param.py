from typing import Literal, Optional, Dict, Any
import os

PROJECT_NAME = 'wechatauto'

class WxParam:
    # 语言设置
    LANGUAGE: Literal['cn', 'cn_t', 'en'] = 'cn'

    # 是否启用日志文件
    ENABLE_FILE_LOGGER: bool = True

    # 下载文件/图片默认保存路径
    DEFAULT_SAVE_PATH: str = os.path.join(os.getcwd(), 'wechatauto文件下载')

    # 是否启用消息哈希值用于辅助判断消息，开启后会稍微影响性能
    MESSAGE_HASH: bool = False

    # 头像到消息X偏移量，用于消息定位，点击消息等操作
    DEFAULT_MESSAGE_XBIAS = 51
    DEFAULT_MESSAGE_YBIAS = 30

    # 是否强制重新自动获取X偏移量，如果设置为True，则每次启动都会重新获取
    FORCE_MESSAGE_XBIAS: bool = False

    # 监听消息时间间隔，单位秒
    LISTEN_INTERVAL: int = 1

    # 监听执行器线程池大小
    LISTENER_EXCUTOR_WORKERS: int = 4

    # 搜索聊天对象超时时间，单位秒
    SEARCH_CHAT_TIMEOUT: int = 2

    # 微信笔记加载超时时间，单位秒
    NOTE_LOAD_TIMEOUT: int = 30

    # 发送文件超时时间，单位秒
    SEND_FILE_TIMEOUT: int = 10

    # 粘贴后回读校验，相似度达到该阈值才按回车；<=0 表示关闭回读校验
    SEND_CONTENT_RATIO: float = 0.6

    # 是否允许使用 OCR（Windows 自带 WinRT 识别）作为定位/对齐兜底手段
    ENABLE_OCR: bool = True

class WxResponse(dict):
    def __init__(self, status: str, message: str, data: dict = None):
        super().__init__(status=status, message=message, data=data)

    def __str__(self):
        return str(self.to_dict())

    def __repr__(self):
        return str(self.to_dict())

    def to_dict(self):
        return {
            'status': self['status'],
            'message': self['message'],
            'data': self['data']
        }

    def __bool__(self):
        return self.is_success

    @property
    def is_success(self):
        return self['status'] == '成功'

    @property
    def message(self) -> str:
        return self.get('message', '')

    @property
    def status(self) -> str:
        return self.get('status', '')

    @property
    def data(self) -> Optional[dict]:
        return self.get('data')

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(f"'WxResponse' object has no attribute '{item}'")

    @classmethod
    def success(cls, message=None, data: dict = None):
        return cls(status="成功", message=message, data=data)

    @classmethod
    def failure(cls, message: str, data: dict = None):
        return cls(status="失败", message=message, data=data)

    @classmethod
    def error(cls, message: str, data: dict = None):
        return cls(status="错误", message=message, data=data)
