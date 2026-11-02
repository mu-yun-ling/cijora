"""Encrypt local provider credentials; the key never enters the web directory."""
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken


class Vault:
    def __init__(self, directory):
        path = Path(directory) / "vault.key"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(Fernet.generate_key())
        self.cipher = Fernet(path.read_bytes())

    def encrypt(self, value):
        return self.cipher.encrypt(value.encode()).decode() if value else ""

    def decrypt(self, value):
        if not value:
            return ""
        try:
            return self.cipher.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("本地密钥无法解密，请在设置中重新保存 API Key") from exc
