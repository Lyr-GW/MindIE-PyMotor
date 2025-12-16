# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

import sys
import logging
import requests


"""
Set the timeout to 600s, which is sufficiently long. 
In probe detection, the timeout for the instance is managed
by the failureThreshold parameter,which defaults to 1s if not configured.
"""
TIMEOUT = 600

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def send_http_request(ip: str, port: str, url_path: str) -> bool:
    url = f"http://{ip}:{port}{url_path}"
    
    headers = {
        'User-Agent': 'sh-probe',
        'Content-Type': 'application/json'
    }
    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=TIMEOUT
        )
        
        if response.status_code == 200:
            return True
        else:
            logger.error(f"HTTP request failed with status code: {response.status_code}")
            
    except requests.exceptions.Timeout:
        logger.error(f"HTTP request timed out after {TIMEOUT} seconds")
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    
    return False


def main():
    if len(sys.argv) != 4:
        logger.error("Usage: python3 probe_status_check.py <ip> <port> <url_path>")
        sys.exit(1)
    
    ip = sys.argv[1]
    port = sys.argv[2]
    url_path = sys.argv[3]
    
    success = send_http_request(ip, port, url_path)
    
    if success:
        sys.exit(0)  # success
    else:
        sys.exit(1)  # fail


if __name__ == "__main__":
    main()