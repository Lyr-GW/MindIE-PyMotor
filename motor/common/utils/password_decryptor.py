# coding=utf-8

# Copyright (c) 2025 Huawei Technologies Co., Ltd
# All rights reserved.

import os
from motor.common.utils.logger import get_logger

logger = get_logger(__name__)


class PasswordDecryptor:

    @staticmethod
    def decrypt(password_file: str) -> str:
        """
        Decrypt the password from the password file, and return the password as a string
        
        Args:
            password_file: The path to the password file
            
        Returns:
            The decrypted password as a string
        """
        try:
            if not os.path.exists(password_file):
                logger.error(f"Password file does not exist: {password_file}")
                return ""
            with open(password_file, "r") as f:
                password = f.read().strip()
            return password
        except Exception as e:
            logger.error(f"Failed to decrypt password: {e}")
            return ""