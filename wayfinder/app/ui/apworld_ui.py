"""Provide apworld ui support."""
from wayfinder.utils.ignored import ignored as _ignored
"""Import-free APWorld inventory and isolated test controls."""
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk
from pathlib import Path

from ...runtime.apworld_catalog import STAGES, inventory
from ...runtime.apworld_compatibility import (dependency_preflight, report_directory, run_compatibility_test,
    environment_identity, COMPATIBILITY_TESTER_VERSION)
from ...diagnostics import sanitize
from ... import setup
from ... import __version__ as WAYFINDER_VERSION


from .ap_inspector_ui import APInspectorUI

class APWorldUI(APInspectorUI):
    """Provide a p world u i behavior."""
    def _build_apworlds(self):
        """Handle build apworlds."""
        page = self._page('APWorlds')
        ttk.Label(page, text='APWorld discovery & compatibility', style='Title.TLabel').pack(anchor='w')
        ttk.Label(page, text=' → '.join(STAGES), wraplength=1100).pack(anchor='w', pady=6)
        ttk.Label(page, text='Tests use default options in separate runtime processes. Active means a live seed has produced validated logic.', wraplength=1100).pack(anchor='w')
        ttk.Label(page, text='Sync updates external custom APWorld archives. Update bundled worlds by importing the matching core in WayFinder Setup.', wraplength=1100).pack(anchor='w')
        controls = ttk.Frame(page)
        controls.pack(fill='x', pady=8)
        self.aw_buttons = []
        for title, action in (('Refresh inventory', self._aw_refresh), ('Sync APWorlds', self._aw_sync),
                              ('Test APWorld', self._aw_test_selected), ('Test All APWorlds', self._aw_test_all)):
            button = ttk.Button(controls, text=title, command=action)
            button.pack(side='left', padx=(0, 6))
            self.aw_buttons.append(button)
        ttk.Button(controls, text='Cancel', command=lambda: self.aw_cancel.set()).pack(side='left')
        self.aw_status = tk.StringVar(value='Refresh inventory to scan installed worlds without importing Python.')
        ttk.Label(page, textvariable=self.aw_status, wraplength=1100).pack(anchor='w', pady=(4, 2))
        progress_row = ttk.Frame(page)
        progress_row.pack(fill='x', pady=(0, 6))
        self.aw_progress = tk.DoubleVar(value=0.0)
        self.aw_progress_bar = ttk.Progressbar(progress_row, variable=self.aw_progress, maximum=100.0, mode='determinate')
        self.aw_progress_bar.pack(side='left', fill='x', expand=True)
        self.aw_progress_text = tk.StringVar(value='Idle')
        ttk.Label(progress_row, textvariable=self.aw_progress_text, width=18, anchor='e').pack(side='left', padx=(8, 0))
        box = ttk.Frame(page)
        box.pack(fill='both', expand=True)
        columns = ('game', 'version', 'source', 'state', 'selection', 'sync')
        self.aw_tree = ttk.Treeview(box, columns=columns, show='headings', height=10)
        for name, width in zip(columns, (260, 95, 110, 160, 160, 120)):
            self.aw_tree.heading(name, text=name.title())
            self.aw_tree.column(name, width=width, minwidth=65)
        scrollbar = ttk.Scrollbar(box, orient='vertical', command=self.aw_tree.yview)
        self.aw_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.aw_tree.pack(fill='both', expand=True)
        self.aw_tree.tag_configure('error', foreground='#d9534f')
        self.aw_tree.tag_configure('warning', foreground='#b57c16')
        self.aw_tree.tag_configure('ready', foreground='#29935a')
        self.aw_tree.bind('<<TreeviewSelect>>', lambda event: self._aw_details())
        details_box = ttk.Frame(page)
        details_box.pack(fill='both', expand=True, pady=8)
        self.aw_details = tk.Text(details_box, height=14, wrap='word', state='disabled')
        details_scroll = ttk.Scrollbar(details_box, command=self.aw_details.yview)
        self.aw_details.configure(yscrollcommand=details_scroll.set)
        details_scroll.pack(side='right', fill='y')
        self.aw_details.pack(fill='both', expand=True)
        self.aw_queue = queue.Queue()
        self.aw_cancel = threading.Event()
        self.aw_records = []
        self.aw_reports = {}
        self.aw_dependencies = {}
        self.aw_busy = False
        self.aw_live_report_ids = set()
        self.root.after(200, self._aw_poll)

    def _aw_start(self, action):
        """Handle aw start."""
        if self.aw_busy:
            return
        self.aw_busy = True
        self.aw_cancel.clear()
        for button in self.aw_buttons:
            button.configure(state='disabled')
        def worker():
            """Handle worker."""
            try:
                action()
            except Exception as exc:
                self.aw_queue.put(('status', 'APWorld operation failed: ' + str(exc)))
            finally:
                self.aw_queue.put(('done', None))
        threading.Thread(target=worker, daemon=True, name='APWorld inventory').start()

    def _aw_scan_worker(self):
        """Handle aw scan worker."""
        self.aw_queue.put(('status', 'Reading APWorld manifests and comparing file hashes…'))
        self.aw_queue.put(('progress', (0, 1, 'Preparing APWorld inventory…')))
        self.aw_queue.put(('log', '[APWorld] Inventory scan started: reading manifests and comparing SHA-256 hashes.'))
        def scan_progress(done, total, label, source):
            """Return scan progress."""
            self.aw_queue.put(('progress', (done, total, label)))
            self.aw_queue.put(('log', f'[APWorld] [{done}/{total}] {source}: {label}'))
        records = inventory(setup.AP_CORE_SOURCE, setup.find_archipelago(), progress=scan_progress)
        current_environment = json.loads(json.dumps(environment_identity(setup.AP_CORE_SOURCE, setup.DEPENDENCIES_DIR)))
        reports = {}
        for path in sorted(report_directory().glob('*.json'), key=lambda p: p.stat().st_mtime):
            if path.name.endswith('.request.json'):
                continue
            try:
                report = json.loads(path.read_text(encoding='utf-8'))
                if report.get('path'):
                    report['report_path'] = str(path)
                    stale_reason = None
                    if report.get('tester_version') != COMPATIBILITY_TESTER_VERSION:
                        stale_reason = 'compatibility tester changed'
                    elif report.get('environment') and report['environment'] != current_environment:
                        stale_reason = 'environment changed'
                    if stale_reason:
                        report['previous_outcome'] = report.get('outcome')
                        report['outcome'] = 'Stale test — retest required'
                        report['stale_reason'] = stale_reason
                    reports[(report['path'], report.get('world_hash'))] = report
            except (OSError, ValueError):
                continue
        dependencies = {}
        dependency_total = max(1, len(records))
        self.aw_queue.put(('log', f'[APWorld] Manifest/hash phase complete: {len(records)} copies detected. Starting dependency preflight.'))
        for dependency_index, record in enumerate(records, 1):
            if self.aw_cancel.is_set():
                break
            self.aw_queue.put(('progress', (dependency_index, dependency_total, f'Dependency preflight: {record.game or Path(record.path).name}')))
            if dependency_index == 1 or dependency_index == dependency_total or dependency_index % 5 == 0:
                self.aw_queue.put(('log', f'[APWorld] Dependency preflight [{dependency_index}/{dependency_total}]: {record.game or Path(record.path).name}'))
            try:
                dependencies[record.path] = dependency_preflight(record, setup.DEPENDENCIES_DIR)
            except Exception as exc:
                dependencies[record.path] = [{'owner':record.game, 'requirement':'Preflight', 'state':str(exc)}]
        self.aw_queue.put(('inventory', (records, reports, dependencies)))
        self.aw_queue.put(('progress', (1, 1, 'Complete')))
        self.aw_queue.put(('log', f'[APWorld] Inventory scan complete: {len(records)} copies checked.'))
        self.aw_queue.put(('status', f'{len(records)} APWorld copies detected. Select one for paths, hashes, dependency owners and test results.'))

    def _aw_refresh(self):
        """Handle aw refresh."""
        self._aw_start(self._aw_scan_worker)

    def _aw_sync(self):
        """Handle aw sync."""
        process = getattr(self, '_managed_runtime_process', None)
        if getattr(self.snapshot, 'connected', False) or (process and process.poll() is None):
            self.aw_status.set('Stop the native runtime before syncing APWorlds; loaded Python packages need a fresh runtime.')
            return
        def work():
            """Handle work."""
            setup.sync_custom_worlds(setup.find_archipelago())
            self._aw_scan_worker()
        self._aw_start(work)

    def _aw_selected(self):
        """Handle aw selected."""
        selected = self.aw_tree.selection()
        return self.aw_records[int(selected[0])] if selected else None

    def _aw_test_selected(self):
        """Handle aw test selected."""
        record = self._aw_selected()
        if record is None:
            self.aw_status.set('Select an APWorld first.')
            return
        if record.source != 'WayFinder':
            record = next((r for r in self.aw_records if r.path == record.mirror_path and r.sha256 == record.sha256), None)
            if record is None:
                self.aw_status.set('Sync this external APWorld first, then test its WayFinder copy.')
                return
        self._aw_run_tests([record])

    def _aw_test_all(self):
        """Handle aw test all."""
        records = [r for r in self.aw_records if r.source == 'WayFinder']
        if not records:
            self.aw_status.set('Refresh inventory and sync APWorlds before testing.')
            return
        self._aw_run_tests(records)

    def _aw_run_tests(self, records):
        """Handle aw run tests."""
        def work():
            """Handle work."""
            completed = 0
            passed = 0
            for index, record in enumerate(records, 1):
                if self.aw_cancel.is_set():
                    break
                self.aw_queue.put(('status', f'Testing {index}/{len(records)}: {record.game or Path(record.path).name} (up to 3 minutes per world)…'))
                report = run_compatibility_test(record, setup.AP_CORE_SOURCE, setup.DEPENDENCIES_DIR, self.aw_cancel)
                self.aw_queue.put(('report', report))
                completed += 1
                passed += report['outcome'].startswith('Passed')
            self.aw_queue.put(('status', f'{completed}/{len(records)} staged APWorlds tested; {passed} passed the default profile. Reports: {report_directory()}'))
        self._aw_start(work)

    def _aw_poll(self):
        """Handle aw poll."""
        if getattr(self, '_closing', False):
            self.aw_cancel.set()
            return
        try:
            while True:
                kind, value = self.aw_queue.get_nowait()
                if kind == 'inventory':
                    self.aw_records, self.aw_reports, self.aw_dependencies = value
                    self._aw_render()
                elif kind == 'report':
                    self.aw_reports[(value['path'], value.get('world_hash'))] = value
                    self._aw_render()
                elif kind == 'status':
                    self.aw_status.set(sanitize(value))
                elif kind == 'progress':
                    done, total, label = value
                    percent = 100.0 if total <= 0 else max(0.0, min(100.0, (float(done) / float(total)) * 100.0))
                    self.aw_progress.set(percent)
                    self.aw_progress_text.set(f'{int(percent)}% · {done}/{total}')
                    if label:
                        self.aw_status.set(sanitize(label))
                elif kind == 'log':
                    self._append_log(sanitize(value), category='APWORLD', level='INFO')
                elif kind == 'done':
                    self.aw_busy = False
                    for button in self.aw_buttons:
                        button.configure(state='normal')
        except queue.Empty:
            _ignored("intentional best-effort fallback")
        self.root.after(200, self._aw_poll)

    def _aw_render(self):
        """Handle aw render."""
        selected = self.aw_tree.selection()
        self.aw_tree.delete(*self.aw_tree.get_children())
        for index, record in enumerate(self.aw_records):
            report = self.aw_reports.get((record.path, record.sha256), {})
            stages = report.get('stages', [])
            state = report.get('outcome') or record.state
            if state == 'Active' and report.get('id') not in self.aw_live_report_ids:
                state = 'Active (previous runtime)'
            if state == 'Running' and stages:
                state = stages[-1] + ' (last recorded)'
            tag = 'error' if record.error or state in {'Failed', 'Timed out'} or 'crashed' in state else 'warning' if record.duplicate_count or record.sync_state == 'Stale copy' else 'ready'
            choice = ('Selected' if record.selected else 'Shadowed by newer/selected version') + (f' · {record.duplicate_count + 1} copies' if record.duplicate_count else '')
            self.aw_tree.insert('', 'end', iid=str(index), values=(record.game or Path(record.path).name, record.version or 'Unversioned', record.source, state, choice, record.sync_state or 'Local'), tags=(tag,))
        if selected and self.aw_tree.exists(selected[0]):
            self.aw_tree.selection_set(selected[0])
        self._aw_details()

    def _aw_details(self):
        """Handle aw details."""
        record = self._aw_selected()
        if record is None:
            return
        report = self.aw_reports.get((record.path, record.sha256), {})
        lines = [record.game or 'Unidentified APWorld',
                 'Identity: ' + ('archipelago.json' if record.manifest else 'Legacy literal fallback'),
                 'Stages: ' + ' → '.join(report.get('stages', [record.state])),
                 'Version: ' + (record.version or 'Unversioned') + ' | Core bounds: ' + str(record.manifest.get('minimum_ap_version', 'any')) + ' to ' + str(record.manifest.get('maximum_ap_version', 'any')),
                 'Aliases: ' + (', '.join(record.aliases) or 'Normalized punctuation/case fallback'), '']
        source_path = record.path if record.source == 'Archipelago' else record.mirror_path
        runtime_path = record.mirror_path if record.source == 'Archipelago' else record.path
        source_hash = record.sha256 if record.source == 'Archipelago' else record.mirror_hash
        runtime_hash = record.mirror_hash if record.source == 'Archipelago' else record.sha256
        lines += ['SOURCE → WAYFINDER RUNTIME', source_path or 'Imported/local source (no external mirror)',
                  'SHA-256: ' + (source_hash or '—'), '↓ ' + (record.sync_state or 'Local installation'),
                  runtime_path or 'Not staged', 'SHA-256: ' + (runtime_hash or '—'), '', 'DEPENDENCY OWNERSHIP']
        dependencies = self.aw_dependencies.get(record.path, [])
        lines += [f"{d['requirement']} ← {d['owner']}: {d['state']} {d.get('installed', '')}" for d in dependencies]
        if not dependencies:
            lines.append('No declared requirements. Import and reconstruction tests check undeclared dependencies.')
        if record.error:
            lines += ['', 'Discovery/core compatibility error: ' + record.error]
        lines += ['', 'COMPATIBILITY REPORT',
                  f'Current tester: v{COMPATIBILITY_TESTER_VERSION} · WayFinder {WAYFINDER_VERSION}',
                  json.dumps(report, indent=2, ensure_ascii=False) if report else 'Not tested for this APWorld hash.']
        self.aw_details.configure(state='normal')
        self.aw_details.delete('1.0', 'end')
        self.aw_details.insert('1.0', sanitize('\n'.join(lines)))
        self.aw_details.configure(state='disabled')

    def _aw_runtime_status(self, name, value):
        """Handle aw runtime status."""
        if name == 'runtime_state' and isinstance(value, dict) and value.get('current') in {'OFFLINE', 'STARTING', 'READY', 'ERROR'} and hasattr(self, 'aw_live_report_ids'):
            self.aw_live_report_ids.clear()
            self._aw_render()
        if name == 'apworld_stage' and isinstance(value, dict) and hasattr(self, 'aw_reports'):
            self.aw_live_report_ids.add(value.get('id'))
            self.aw_reports[(value['path'], value.get('world_hash'))] = value
            self._aw_render()
        elif name == 'apworld_error_report' and hasattr(self, 'aw_status'):
            self.aw_status.set('Runtime reconstruction error saved: ' + str(value))
