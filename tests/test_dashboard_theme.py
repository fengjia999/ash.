import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node.js is required")
class DashboardThemeTests(unittest.TestCase):
    def run_theme(self, setup, assertions):
        source = (Path(__file__).resolve().parents[1] / "static/js/theme.js").read_text()
        harness = r"""
const assert = require('node:assert/strict');
const events = {}, windowEvents = {}, attributes = {};
let click;
const frames = [], synced = [];
const meta = {};
const button = {setAttribute:(key,value)=>{attributes[key]=value;}, addEventListener:(name,fn)=>{if(name==='click')click=fn;}};
const document = {
    documentElement:{dataset:{}},
    querySelector:()=>meta,
    querySelectorAll:()=>frames,
    getElementById:()=>button,
    addEventListener:(name,fn)=>{events[name]=fn;},
};
let systemChanged;
const system = {matches:false,addEventListener:(name,fn)=>{systemChanged=fn;}};
const notifications = [];
const CustomEvent = class {constructor(type,options){this.type=type;this.detail=options.detail;}};
const window = {matchMedia:()=>system,dispatchEvent:event=>notifications.push(event),addEventListener:(name,fn)=>{windowEvents[name]=fn;}};
window.parent = window;
const saved = new Map();
const localStorage = {getItem:key=>saved.get(key),setItem:(key,value)=>saved.set(key,value)};
"""
        result = subprocess.run(["node", "-"], input=harness + setup + source + assertions,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_saved_theme_click_and_late_frame_loading_stay_synchronized(self):
        self.run_theme(r"""
saved.set('ash-dashboard-theme','dark');
frames.push({contentWindow:{AshTheme:{setTheme:(theme,options)=>synced.push([theme,options.persist])}}});
""", r"""
assert.equal(document.documentElement.dataset.theme,'dark');
events.DOMContentLoaded();
assert.equal(attributes['aria-pressed'],'true');
assert.equal(attributes['aria-label'],'切换到日间模式');
click();
assert.equal(saved.get('ash-dashboard-theme'),'light');
assert.equal(document.documentElement.dataset.theme,'light');
assert.equal(meta.content,'#f4f3ee');
assert.deepEqual(synced.at(-1),['light',false]);
events.load({target:{tagName:'IFRAME',contentWindow:{AshTheme:{setTheme:theme=>synced.push(theme)}}}});
assert.equal(synced.at(-1),'light');
windowEvents.storage({key:'ash-dashboard-theme',newValue:'dark'});
assert.equal(document.documentElement.dataset.theme,'dark');
assert.equal(saved.get('ash-dashboard-theme'),'light','storage events do not write back');
""")

    def test_iframe_inherits_parent_even_when_storage_is_unavailable(self):
        self.run_theme(r"""
localStorage.getItem=localStorage.setItem=()=>{throw new Error('storage unavailable');};
window.parent={document:{documentElement:{dataset:{theme:'dark'}}}};
""", r"""
assert.equal(document.documentElement.dataset.theme,'dark');
events.DOMContentLoaded();
click();
assert.equal(document.documentElement.dataset.theme,'light');
assert.equal(attributes['aria-pressed'],'false');
window.AshTheme.setTheme('invalid');
assert.equal(document.documentElement.dataset.theme,'light');
""")

    def test_auto_tracks_system_changes_but_manual_choice_does_not(self):
        self.run_theme("system.matches=true;", r"""
assert.equal(window.AshTheme.getPreference(),'auto');
assert.equal(document.documentElement.dataset.theme,'dark');
system.matches=false;systemChanged();
assert.equal(document.documentElement.dataset.theme,'light');
window.AshTheme.setTheme('dark');
systemChanged();
assert.equal(document.documentElement.dataset.theme,'dark');
window.AshTheme.setTheme('auto');
assert.equal(saved.get('ash-dashboard-theme'),'auto');
assert.equal(document.documentElement.dataset.theme,'light');
system.matches=true;windowEvents.pageshow();
assert.equal(document.documentElement.dataset.theme,'dark');
system.matches=false;events.visibilitychange();
assert.equal(document.documentElement.dataset.theme,'light');
assert.equal(saved.get('ash-dashboard-theme'),'auto');
assert.deepEqual(notifications.at(-1).detail,{preference:'auto',theme:'light'});
""")

    def test_old_desktop_preference_migrates_without_overriding_global_choice(self):
        self.run_theme("saved.set('ash.phone.desktop.v2',JSON.stringify({mode:'dark'}));", r"""
assert.equal(window.AshTheme.getPreference(),'dark');
assert.equal(saved.get('ash-dashboard-theme'),'dark');
""")
        self.run_theme("saved.set('ash-dashboard-theme','light');saved.set('ash.phone.desktop.v2','broken');", r"""
assert.equal(window.AshTheme.getPreference(),'light');
""")

    def test_auto_inheritance_storage_reset_and_late_frames(self):
        self.run_theme(r"""
system.matches=true;
saved.set('ash-dashboard-theme','light');
window.parent={AshTheme:{getPreference:()=> 'auto'},document:{documentElement:{dataset:{theme:'dark'}}}};
""", r"""
assert.equal(window.AshTheme.getPreference(),'auto');
assert.equal(document.documentElement.dataset.theme,'dark');
events.load({target:{tagName:'IFRAME',contentWindow:{AshTheme:{setTheme:(value,options)=>synced.push([value,options.persist])}}}});
assert.deepEqual(synced.at(-1),['auto',false]);
windowEvents.storage({key:'ash-dashboard-theme',newValue:'light'});
assert.equal(document.documentElement.dataset.theme,'light');
windowEvents.storage({key:'ash-dashboard-theme',newValue:null});
assert.equal(document.documentElement.dataset.theme,'dark');
assert.equal(saved.get('ash-dashboard-theme'),'light');
""")
