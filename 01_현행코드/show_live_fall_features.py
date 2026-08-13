# -*- coding: utf-8 -*-
"""sender 로그에서 낙상 판정 피처만 실시간 표시한다. 실행 환경: 젯슨 터미널."""
import os
import time

PATH = os.path.expanduser('~/jetson_sender_safety.log')


def main():
    while not os.path.exists(PATH):
        time.sleep(0.5)
    with open(PATH, encoding='utf-8', errors='replace') as fh:
        fh.seek(0, os.SEEK_END)
        while True:
            line = fh.readline()
            if not line:
                time.sleep(0.1)
                continue
            if '[FALL-FEAT]' in line:
                print(line.rstrip(), flush=True)


if __name__ == '__main__':
    main()
