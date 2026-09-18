"""Provide test diagnostics logging support."""
import io
import unittest
from wayfinder.diagnostics import sanitize, register_secret, make_record, format_record, CATEGORIES
import ast
import threading
from pathlib import Path
source=Path(__file__).resolve().parents[2].joinpath("run_wayfinder.py").read_text(encoding="utf-8")
node=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=="_BootTeeStream")
namespace=dict(TextIO=object, _BOOT_LOG_LOCK=threading.RLock(), sanitize=sanitize, make_record=make_record, format_record=format_record)
exec(compile(ast.Module(body=[node],type_ignores=[]),"boot_stream","exec"),namespace)
_BootTeeStream=namespace["_BootTeeStream"]

class DiagnosticsTests(unittest.TestCase):
    """Provide diagnostics tests behavior."""
    def test_nested_secrets(self):
        """Handle test nested secrets."""
        original={'password':'hidden', 'nested':[{'access_token':'abc', 'count':3}]}
        clean=sanitize(original)
        self.assertEqual(clean['password'],'[REDACTED]')
        self.assertEqual(clean['nested'][0]['access_token'],'[REDACTED]')
        self.assertEqual(original['password'],'hidden')

    def test_free_text_secrets(self):
        """Handle test free text secrets."""
        for text, secret in [('password="two words"','two words'), ('token=abcd&x=1','abcd'), ('Authorization: Bearer xyz123','xyz123'), ('https://joe:pass123@example.com','pass123'), ('/password some pass','some pass'), ('{"api_key": "key123"}','key123')]:
            self.assertNotIn(secret,sanitize(text))
        register_secret('unique-private-value')
        self.assertNotIn('unique-private-value',sanitize('Echo unique-private-value'))

    def test_categories_and_levels(self):
        """Handle test categories and levels."""
        for category in CATEGORIES:
            record=make_record('operation complete',category)
            self.assertEqual(record['category'],category)
            self.assertIn('['+category+']',format_record(record))
        self.assertEqual(make_record('APWorld build failed')['level'],'ERROR')
        self.assertEqual(make_record('APWorld build failed')['category'],'APWORLD')
        self.assertEqual(make_record('dependency timeout')['level'],'WARNING')

    def test_split_boot_write(self):
        """Handle test split boot write."""
        console, disk=io.StringIO(),io.StringIO()
        stream=_BootTeeStream(console,[disk])
        stream.write('pass'); stream.flush(); stream.write('word=super'); stream.flush(); stream.write('secret\n')
        self.assertNotIn('supersecret',console.getvalue()+disk.getvalue())
        self.assertIn('[REDACTED]',disk.getvalue())

    def test_recent_errors_and_bounded_records(self):
        """Handle test recent errors and bounded records."""
        from wayfinder.app.app import WayFinderApp
        app=WayFinderApp.__new__(WayFinderApp)
        app.log_lines=[]
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            for i in range(60):
                app._append_log('failed token=private',category='AP',level='ERROR')
        self.assertEqual(len(app.recent_errors),50)
        self.assertEqual(len(app.log_records),60)
        self.assertNotIn('private',str(app.log_records))

if __name__=='__main__': unittest.main()
