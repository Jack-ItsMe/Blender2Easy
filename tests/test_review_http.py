import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1] / 'skills' / 'blender2easy'
spec = importlib.util.spec_from_file_location('review_server_http', ROOT/'editor/server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
from animkit.review import create_request, get_review


class ReviewHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.editor = server.Editor(Path(self.temp.name)/'projects')
        raw = json.loads((Path(__file__).parent/'fixtures/motion-request.json').read_text(encoding='utf-8'))
        # Isolate HTTP permissions from custom timing authoring; use one allowed field.
        raw['controls'] = raw['controls'][:1]
        self.review = create_request(self.editor.path, raw, raw['thread_id'])
        self.http = server.ThreadingHTTPServer(('127.0.0.1',0), server.Handler)
        self.http.editor = self.editor
        self.thread = threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.http.server_port}'
        self.initial = server.sha256(self.editor.path)

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join()
        self.temp.cleanup()

    def call(self, path, data=None):
        request = urllib.request.Request(self.base+path, data=None if data is None else json.dumps(data).encode(),
                  headers={'Content-Type':'application/json','X-Editor-Token':self.editor.token})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def payload(self):
        request = self.review['request']
        return {'path':str(self.editor.path),'request_id':request['id'],
                'revision':request['revision'],'values':{'angle':90}}

    def test_default_cannot_escape_into_full_editor(self):
        for route,data in [('/api/save',{'path':str(self.editor.path),'revision':self.initial,'project':{}}),
                           ('/api/new',{'template':'blank'}),('/api/open',{'path':str(self.editor.path)}),
                           ('/api/import-blend',{'path':'anything.blend'}),
                           ('/api/job',{'operation':'run','path':str(self.editor.path),'revision':self.initial})]:
            self.assertEqual(self.call(route,data)[0],403,route)
        self.assertEqual(self.call('/authoring')[0],403)
        self.assertEqual(server.sha256(self.editor.path),self.initial)

    def test_proposal_is_scoped_and_does_not_write_project(self):
        status,result=self.call('/api/review/preview',self.payload())
        self.assertEqual(status,200)
        self.assertEqual({c['path'] for c in result['changes']},
                         {'/scene/animation/0/keys/2/value/0','/scene/animation/0/keys/3/value/0'})
        self.assertEqual(result['project']['scene']['animation'][0]['keys'][2]['value'][0],-90)
        status,result=self.call('/api/review/submit',self.payload()|{'decision':'confirm','note':'动作这样就好'})
        self.assertEqual(status,200)
        self.assertEqual(result['review']['status'],'submitted')
        self.assertFalse(result['review'].get('received_at'))
        self.assertEqual(server.sha256(self.editor.path),self.initial)

    def test_browser_cannot_supply_a_project_or_extra_control(self):
        self.assertEqual(self.call('/api/review/preview',self.payload()|{'project':{}})[0],400)
        self.assertEqual(self.call('/api/review/preview',self.payload()|{'values':{'angle':90,'scale':4}})[0],400)
        self.assertEqual(self.call('/api/review/preview',self.payload()|{'values':{'angle':999}})[0],400)
        self.assertEqual(server.sha256(self.editor.path),self.initial)

    def test_explicit_authoring_still_respects_pending_review(self):
        self.editor.authoring=True
        current=self.editor.response()
        current['project']['render']['samples']=99
        self.assertEqual(self.call('/api/save',{'project':current['project'],'path':current['path'],
                         'revision':current['revision']})[0],409)
        self.assertEqual(server.sha256(self.editor.path),self.initial)

    def test_stale_request_and_wrong_project_are_rejected(self):
        self.assertEqual(self.call('/api/review/preview',self.payload()|{'request_id':'review-old'})[0],409)
        self.assertEqual(self.call('/api/review/preview',self.payload()|{'path':str(self.editor.path.parent/'other.json')})[0],409)
        self.assertEqual(self.call('/api/review/activate',{'path':str(self.editor.path),'request_id':'review-old'})[0],409)

    def test_media_url_keeps_frozen_bytes_when_source_is_replaced(self):
        media = self.editor.path.parent/'render.png'
        media.write_bytes(b'original-render-test')
        raw = json.loads((Path(__file__).parent/'fixtures/delivery-request.json').read_text(encoding='utf-8'))
        raw['media']={'path':str(media)}
        create_request(self.editor.path,raw,raw['thread_id'])
        status,result=self.call('/api/review')
        self.assertEqual(status,200)
        media_url=result['review']['media_url']
        media.write_bytes(b'replacement-render-test')
        self.assertEqual(self.call('/api/review')[0],409)
        with urllib.request.urlopen(self.base+media_url,timeout=5) as response:
            self.assertEqual(response.read(),b'original-render-test')


if __name__=='__main__':
    unittest.main()
