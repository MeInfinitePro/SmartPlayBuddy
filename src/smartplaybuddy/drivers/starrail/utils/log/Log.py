import os
from datetime import datetime
from typing import Optional


class Log:
    """简单日志记录器"""

    def __init__(self, log_file: str = "log.txt", level: str = "info", console_output: bool = True):
        self.log_path = os.path.join(os.path.dirname(__file__), log_file)
        self.level = level.upper()
        self.console_output = console_output  # 控制是否输出到控制台

    def _write(self, message: str, level: str = "info"):
        """写入日志"""
        timestamp = datetime.now().strftime("%Y%m%d %H:%M:%S")
        content = f"{timestamp} |{level.upper()}| {message}\n" if message else f"{timestamp} |{level.upper()}| None\n"
        align_center = 60 // 2 - len(message) // 2
        if level == "title":
            content = " " * align_center + f"{message}" + " " * 10 + "\n"
        if level == "decorate":
            content = message + "\n"

        # 写入文件
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            print(f"日志写入失败: {e}")

        # 输出到控制台
        if self.console_output:
            print(content.strip())  # strip()去掉末尾的换行符，print会自动换行

    def info(self, msg: Optional[str] = None):
        """记录普通信息"""
        self._write(msg, "info")

    def error(self, msg: Optional[str] = None):
        """记录错误信息"""
        self._write(msg, "error")

    def warning(self, msg: Optional[str] = None):
        """记录警告信息"""
        self._write(msg, "warning")

    def debug(self, msg: Optional[str] = None):
        """记录调试信息"""
        self._write(msg, "debug")

    def title(self, msg: Optional[str] = None):
        """记录任务执行的标题"""
        self._write("=" * 60, "decorate")
        self._write(msg, "title")
        self._write("=" * 60, "decorate")


    def clean_log(self):
        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write("")
        except Exception as e:
            print(f"清除失败: {e}")


# 使用示例
if __name__ == "__main__":
    # 默认开启控制台输出
    log = Log(console_output=True)


    # 如果不想输出到控制台，可以关闭
    # log_no_console = Log(console_output=False)
    # log_no_console.info("这条不会在控制台显示")