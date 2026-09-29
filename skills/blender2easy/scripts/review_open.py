"""Open a scoped request in the existing local studio, starting it if needed."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

from animkit import __version__
from animkit.review import get_review, review_url


def open_review(project_path, port=8766, browser=True):
    project_path = Path(project_path).expanduser().resolve()
    review = get_review(project_path)
    if not review:
        raise ValueError('请先创建一个明确范围的调整任务')
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError('Local editor port must be 1024–65535')
    base = f'http://127.0.0.1:{port}'

    def read(route):
        with urllib.request.urlopen(base + route, timeout=3) as response:
            return json.load(response)

    try:
        health = read('/api/health')
    except urllib.error.URLError:
        root = Path(__file__).resolve().parents[1]
        log_path = project_path.parent / '.animation' / 'review' / 'server.log'
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('ab') as log:
            process = subprocess.Popen(
                [sys.executable, '-X', 'utf8', str(root / 'editor/server.py'), '--port', str(port),
                 '--project', str(project_path)], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                start_new_session=os.name != 'nt')
        deadline = time.monotonic() + 10
        while True:
            if process.poll() is not None:
                raise RuntimeError(f'预览服务未能启动，请查看 {log_path}')
            try:
                health = read('/api/health')
                break
            except urllib.error.URLError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f'预览服务启动超时，请查看 {log_path}')
                time.sleep(0.15)
    if health.get('status') != 'READY' or health.get('version') != __version__:
        raise RuntimeError(f'端口 {port} 运行的不是 {__version__} 预览服务，请使用其他端口或重新启动正确版本')
    session = read('/api/session')
    payload = json.dumps({'path':str(project_path), 'request_id':review['request']['id']}).encode('utf-8')
    request = urllib.request.Request(base + '/api/review/activate', data=payload,
        headers={'Content-Type':'application/json', 'X-Editor-Token':session['token']})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            json.load(response)
    except urllib.error.HTTPError as error:
        body = json.load(error)
        raise RuntimeError(body.get('error', '不能打开当前调整任务')) from error
    url = review_url(review['request'], base)
    if browser:
        webbrowser.open(url)
    return {'status':'OPEN', 'url':url, 'project':str(project_path),
            'request_id':review['request']['id'], 'thread_id':review['request']['thread_id']}
