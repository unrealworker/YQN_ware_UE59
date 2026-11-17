"""Exercise the packaged UE page with real browser clicks and visual evidence.

Run with UE's Python (Playwright may live in Saved/UE59Web/python-deps):
  python Scripts/ghs/verify_wasm_warehouse_interactions.py --stage Deployment/GHSWeb59/Wasm --out Saved/UE59Web/interactions --tier deferred

MPR is a native Slate HUD without a JavaScript state binding. Its panel and roof
checks deliberately use rendered pixels; GHS also records the native roof state.
The viewport is fixed at the application's 1920 x 1080 design resolution.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
LOCAL_DEPS = ROOT / 'Saved/UE59Web/python-deps'
if LOCAL_DEPS.is_dir():
    sys.path.insert(0, str(LOCAL_DEPS))
from playwright.sync_api import sync_playwright

IMAGE_ANALYSIS = r"""async ({png,other,rects}) => {
 const decode=async s=>{const img=new Image();img.src=s;await img.decode();const c=new OffscreenCanvas(img.width,img.height);const ctx=c.getContext('2d',{willReadFrequently:true});ctx.drawImage(img,0,0);return {w:img.width,h:img.height,p:ctx.getImageData(0,0,img.width,img.height).data};};
 const a=await decode(png),b=other?await decode(other):null;
 const pixel=(x,y)=>4*(Math.round(y)*a.w+Math.round(x));
 const white=(x,y)=>{const i=pixel(x,y);return a.p[i]>245&&a.p[i+1]>245&&a.p[i+2]>245;};
 const stats=([x,y,w,h])=>{let n=0,whites=0,changed=0,total=0;for(let yy=Math.max(0,y);yy<Math.min(a.h,y+h);yy+=2)for(let xx=Math.max(0,x);xx<Math.min(a.w,x+w);xx+=2){const i=pixel(xx,yy);n++;if(white(xx,yy))whites++;if(b){const d=Math.max(Math.abs(a.p[i]-b.p[i]),Math.abs(a.p[i+1]-b.p[i+1]),Math.abs(a.p[i+2]-b.p[i+2]));if(d>24)changed++;total+=d;}}return {whiteFraction:whites/n,changedFraction:b?changed/n:null,meanMaxChannelDelta:b?total/n:null,samples:n};};
 return {rects:Object.fromEntries(Object.entries(rects||{}).map(([k,v])=>[k,stats(v)]))};
}"""


def encoded(data):
    mime = 'image/jpeg' if data.startswith(b'\xff\xd8\xff') else 'image/png'
    return 'data:' + mime + ';base64,' + base64.b64encode(data).decode('ascii')


def inspect_pixels(page, png, rects=None, other=None):
    return page.evaluate(IMAGE_ANALYSIS, {'png': encoded(png), 'other': encoded(other) if other else None,
                                        'rects': rects or {}})


def snapshot(page, folder, name):
    return page.screenshot(path=str(folder / (name + '.png')), animations='allow')


def native_get(frame, method):
    raw = frame.evaluate("async method=>{const bridge=window.ue&&window.ue.twin;if(!bridge||!bridge[method])throw Error('No '+method);return await Promise.race([bridge[method](),new Promise((_,r)=>setTimeout(()=>r(Error('Native getter timeout')),5000))]);}", method)
    return json.loads(raw)


def globe_frame(page):
    return next(frame for frame in page.frames if frame != page.main_frame and frame.locator('#back').count())


def controls_frame(page, globe):
    for frame in page.frames:
        if frame in (page.main_frame, globe):
            continue
        try:
            if frame.evaluate('()=>!!(window.ue&&window.ue.twin)'):
                native_get(frame, 'getscenecontrolsstate')
                return frame
        except Exception:
            continue
    return None


def visible_countries(frame):
    return frame.locator('#countries .country').evaluate_all("els=>els.map(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return {name:e.textContent,visible:!e.hidden&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity)>.5&&r.width>0&&r.height>0&&r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight,x:r.x,y:r.y};}).filter(e=>e.visible)")


def wait_phase(frame, phases, timeout=120000):
    frame.wait_for_function('phases=>phases.includes(document.body.dataset.phase)', arg=phases, timeout=timeout)


def check_panel(page, folder):
    """The 360px native panel is at (20,80); only its title strip remains closed."""
    body = {'body': [32, 160, 336, 200], 'title': [32, 90, 336, 25]}
    before = snapshot(page, folder, 'mpr-panel-default-collapsed')
    first = inspect_pixels(page, before, body)['rects']
    # The title's right-hand button is an actual native Slate widget.
    page.mouse.click(346, 104)
    page.wait_for_timeout(350)
    expanded = snapshot(page, folder, 'mpr-panel-expanded')
    second = inspect_pixels(page, expanded, body, before)['rects']
    page.mouse.click(346, 104)
    page.wait_for_timeout(350)
    closed = snapshot(page, folder, 'mpr-panel-collapsed-again')
    third = inspect_pixels(page, closed, body, before)['rects']
    evidence = {'button': {'x': 346, 'y': 104}, 'default': first, 'expanded': second, 'collapsedAgain': third}
    (folder / 'panel-result.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    assert first['body']['whiteFraction'] < .75, 'MPR panel body is visible by default'
    assert second['body']['whiteFraction'] > .80, 'Click did not expand the native MPR panel'
    assert second['body']['changedFraction'] > .15, 'Native panel did not visibly change on expand'
    assert third['body']['whiteFraction'] < .75, 'Second click did not collapse the MPR panel'
    return evidence


def capture_roof_click(page, frame, point, folder):
    """CDP records the actual composited frames while a real mouse click opens the roof."""
    client = page.context.new_cdp_session(page)
    images = []
    started = time.monotonic()

    def on_frame(event):
        client.send('Page.screencastFrameAck', {'sessionId': event['sessionId']})
        if len(images) < 45:
            images.append({'time': time.monotonic() - started, 'data': base64.b64decode(event['data']),
                           'timestamp': event.get('metadata', {}).get('timestamp')})

    client.on('Page.screencastFrame', on_frame)
    client.send('Page.enable')
    client.send('Page.startScreencast', {'format': 'jpeg', 'quality': 75, 'maxWidth': 1920, 'maxHeight': 1080, 'everyNthFrame': 1})
    if frame:
        frame.evaluate("()=>{window.__roofCheck={samples:[],pending:false};window.__roofCheck.timer=setInterval(async()=>{const r=window.__roofCheck;if(r.pending)return;r.pending=true;try{r.samples.push({time:performance.now(),state:JSON.parse(await window.ue.twin.getscenecontrolsstate())});}catch(e){r.samples.push({error:String(e)});}finally{r.pending=false;}},45);}")
    page.mouse.click(point['x'], point['y'], delay=40)
    clicked = time.monotonic()
    for offset in (.08, .20, .38, .60, .90, 1.30):
        page.wait_for_timeout(max(1, int((clicked + offset - time.monotonic()) * 1000)))
        images.append({'time': time.monotonic() - started, 'data': page.screenshot(type='jpeg', quality=75, animations='allow'),
                       'timestamp': None, 'source': 'explicit-compositor-screenshot'})
    page.wait_for_timeout(1500)
    client.send('Page.stopScreencast')
    client.detach()
    states = []
    if frame:
        states = frame.evaluate('()=>{clearInterval(window.__roofCheck.timer);return window.__roofCheck.samples;}')
    for index, image in enumerate(images):
        image['file'] = f'roof-animation-{index:02d}.jpg'
        (folder / image['file']).write_bytes(image['data'])
    return images, states


def verify_warehouse(page, globe, warehouse_id, out):
    folder = out / warehouse_id
    folder.mkdir(exist_ok=True)
    # Selection and navigation go through their visible DOM buttons.
    if globe.locator('#clear').is_visible():
        globe.locator('#clear').click()
        wait_phase(globe, ['idle'])
    globe.locator(f'#warehouse-list [data-select="{warehouse_id}"]').click()
    wait_phase(globe, ['selected'])
    selected = native_get(globe, 'getstate')
    assert selected['selectedId'] == warehouse_id
    assert selected['selectionInputSource'] == 'pointer'
    globe.locator('#enter').click()
    wait_phase(globe, ['warehouse'])
    page.wait_for_function("()=>{const f=[...document.querySelectorAll('iframe')].find(e=>e.contentDocument?.querySelector('#back'));if(!f)return false;const r=f.getBoundingClientRect();return r.width<=202&&r.height<=46&&r.x>=20&&r.y>500;}", timeout=30000)
    page.wait_for_timeout(1200)
    entered = native_get(globe, 'getstate')
    result = {'selected': selected, 'entered': entered}
    if warehouse_id == 'mpr-nj':
        result['panel'] = check_panel(page, folder)
    control = controls_frame(page, globe)
    before_state = native_get(control, 'getscenecontrolsstate') if control else None
    if warehouse_id == 'ghs-ca':
        assert before_state is not None, 'GHS native scene state bridge missing'
    if before_state:
        assert before_state['roofClosed'] and not before_state['roofOpening'], 'Roof is not initially closed'
    before = snapshot(page, folder, 'roof-before')
    # Calibrated against each actual 1920x1080 r2 screenshot roof-before.png;
    # verify the visible card before clicking its centre, without engine commands.
    label_rect = [622, 291, 228, 56] if warehouse_id == 'mpr-nj' else [604, 446, 228, 56]
    visible = inspect_pixels(page, before, {'label': label_rect})['rects']['label']
    assert visible['whiteFraction'] > .65, 'Warehouse label no longer matches the observed screenshot coordinates'
    label = {'x': label_rect[0], 'y': label_rect[1], 'width': 228, 'height': 56, 'source': 'observed-r2-screenshot', **visible}
    point = {'x': label['x'] + 114, 'y': label['y'] + 28}
    frames, states = capture_roof_click(page, control, point, folder)
    after = snapshot(page, folder, 'roof-after')
    after_state = native_get(control, 'getscenecontrolsstate') if control else None
    # Exclude application chrome and the simulation panel. A roof covers far more
    # pixels than a moving vehicle; this threshold catches a non-working click.
    roi = [400, 220, 1000 if warehouse_id == 'ghs-ca' else 1350, 650]
    scene_delta = inspect_pixels(page, after, {'roofScene': roi}, before)['rects']['roofScene']
    checkpoint = {'beforeState': before_state, 'afterState': after_state, 'label': label, 'click': point,
                  'sceneDelta': scene_delta, 'statesDuringAnimation': states,
                  'frames': [{key: value for key, value in image.items() if key != 'data'} for image in frames]}
    (folder / 'roof-result.json').write_text(json.dumps(checkpoint, indent=2), encoding='utf-8')
    assert scene_delta['changedFraction'] > .035, 'Warehouse roof did not visibly open'
    label_after = inspect_pixels(page, after, {'label': label_rect})['rects']['label']
    assert label_after['whiteFraction'] < visible['whiteFraction'] - .20, 'Closed-roof label remains after clicking'
    if after_state:
        assert not after_state['roofClosed'] and not after_state['roofOpening'] and not after_state['roofClosing'], 'Native roof has not completed opening'
        assert any(item.get('state', {}).get('roofOpening') for item in states), 'No intermediate native opening state observed'
    intermediate = []
    for index, frame in enumerate(frames):
        # Sampling all received frames also works when WebGPU delivers fewer FPS.
        from_before = inspect_pixels(page, frame['data'], {'roofScene': roi}, before)['rects']['roofScene']['changedFraction']
        from_after = inspect_pixels(page, frame['data'], {'roofScene': roi}, after)['rects']['roofScene']['changedFraction']
        # JPEG noise and moving vehicles alone must not count as a dissolve.
        if from_before > .04 and from_after > .04:
            intermediate.append({'index': index, 'file': frame['file'], 'fromBefore': from_before, 'fromAfter': from_after})
    assert intermediate, 'No visually distinct intermediate roof dissolve frame captured'
    result.update({'pass': True, 'label': label, 'click': point, 'beforeState': before_state, 'afterState': after_state,
                   'stateBinding': 'native' if control else 'MPR native-only HUD: visual verification',
                   'sceneDelta': scene_delta, 'statesDuringAnimation': states, 'intermediateFrames': intermediate,
                   'frames': [{key: value for key, value in frame.items() if key != 'data'} for frame in frames]})
    globe.locator('#back').click()
    wait_phase(globe, ['selected', 'idle'])
    page.wait_for_timeout(500)
    result['returned'] = native_get(globe, 'getstate')
    assert result['returned']['stageVisible']
    result['returnCountries'] = visible_countries(globe)
    assert result['returnCountries'], 'Country names disappeared after returning to globe'
    snapshot(page, folder, 'returned-to-globe')
    (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--tier', choices=['deferred', 'forward'], default='deferred')
    parser.add_argument('--engine', type=Path, default=Path('C:/UE/UE_5.9'))
    parser.add_argument('--browser', type=Path, default=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'))
    parser.add_argument('--browser-arg', action='append', default=[], help='Additional isolated-browser argument; use --browser-arg=--flag')
    parser.add_argument('--warehouse', action='append', choices=['mpr-nj', 'ghs-ca'], help='Run selected warehouse(s); default: both')
    args = parser.parse_args()
    args.stage = args.stage.resolve()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    assert (args.stage / 'index.html').is_file(), f'No packaged index.html in {args.stage}'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    log = (args.out / 'server.log').open('w', encoding='utf-8')
    server = subprocess.Popen([sys.executable, str(args.engine / 'Engine/Platforms/Wasm/Build/Tools/web/serve.py'),
                               '--root', str(args.stage), '--port', str(port)], stdout=log, stderr=log,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    url = f'http://127.0.0.1:{port}'
    errors, failures, console = [], [], []
    result = {'stage': str(args.stage), 'tier': args.tier, 'viewport': {'width': 1920, 'height': 1080},
              'extraBrowserArguments': args.browser_arg, 'pass': False}
    page = None
    try:
        for attempt in range(100):
            try:
                with urllib.request.urlopen(url + '/index.html', timeout=1):
                    break
            except Exception:
                time.sleep(.1)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch_persistent_context(str(args.out / 'browser-profile'),
                executable_path=str(args.browser), headless=True, viewport=result['viewport'],
                args=['--enable-unsafe-webgpu', '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
                      '--disable-backgrounding-occluded-windows', '--headless=new',
                      '--autoplay-policy=no-user-gesture-required', '--enable-features=SharedArrayBuffer'] + args.browser_arg)
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('requestfailed', lambda request: failures.append({'url': request.url, 'failure': request.failure}))
            page.on('console', lambda message: console.append(message.type + ': ' + message.text))
            print('Opening packaged page', flush=True)
            page.goto(url + '/index.html?tier=' + args.tier)
            result['adapter'] = page.evaluate("async()=>{const a=await navigator.gpu?.requestAdapter({powerPreference:'high-performance'});return a?{vendor:a.info.vendor,architecture:a.info.architecture,description:a.info.description,isFallbackAdapter:a.info.isFallbackAdapter}:null;}")
            page.wait_for_function("document.querySelector('iframe')?.contentDocument?.body?.dataset.ready==='true'||document.body.innerText.includes(\"can't run on this GPU\")", timeout=150000)
            assert not page.get_by_text("can't run on this GPU", exact=False).count(), 'Browser cannot access a usable WebGPU adapter'
            page.wait_for_function("document.getElementById('cover').hidden||document.getElementById('cover').classList.contains('click')", timeout=30000)
            if not page.locator('#cover').evaluate('(e)=>e.hidden'):
                page.locator('#cover').click(position={'x': 960, 'y': 540})
            page.wait_for_function("document.getElementById('cover').hidden", timeout=10000)
            globe = globe_frame(page)
            wait_phase(globe, ['idle', 'selected'])
            page.wait_for_timeout(800)
            result['initialState'] = native_get(globe, 'getstate')
            result['initialCountries'] = visible_countries(globe)
            snapshot(page, args.out, 'globe-country-labels')
            assert result['initialCountries'], 'Initial globe has no visible country names'
            result['warehouses'] = {}
            for warehouse_id in args.warehouse or ['mpr-nj', 'ghs-ca']:
                print('Verifying ' + warehouse_id, flush=True)
                try:
                    result['warehouses'][warehouse_id] = verify_warehouse(page, globe, warehouse_id, args.out)
                except Exception as error:
                    result['warehouses'][warehouse_id] = {'pass': False, 'error': str(error), 'traceback': traceback.format_exc()}
                    snapshot(page, args.out / warehouse_id, 'failure')
                    if globe.evaluate("()=>document.body.dataset.phase") == 'warehouse':
                        globe.locator('#back').click()
                        wait_phase(globe, ['selected', 'idle'])
                        page.wait_for_timeout(800)
                        result['warehouses'][warehouse_id]['returned'] = native_get(globe, 'getstate')
                        result['warehouses'][warehouse_id]['returnCountries'] = visible_countries(globe)
                        snapshot(page, args.out / warehouse_id, 'returned-to-globe-after-incomplete-check')
            assert not errors, f'Uncaught page errors: {errors}'
            result['pass'] = all(item['pass'] for item in result['warehouses'].values())
            browser.close()
    except Exception as error:
        result['error'] = str(error)
        result['traceback'] = traceback.format_exc()
        if page and not page.is_closed():
            try:
                snapshot(page, args.out, 'failure')
            except Exception:
                pass
    finally:
        result['pageErrors'] = errors
        result['failedRequests'] = failures
        (args.out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        (args.out / 'console.log').write_text('\n'.join(console), encoding='utf-8')
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        log.close()
    print(json.dumps({'pass': result['pass'], 'error': result.get('error'), 'out': str(args.out)}, ensure_ascii=True), flush=True)
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
