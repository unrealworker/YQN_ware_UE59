#include "SGHSWasmBrowser.h"

#if PLATFORM_WASM
#include "GHSTwinHUDWidget.h"
#include "GHSGlobeNavigation.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Misc/App.h"
#include "Misc/CoreDelegates.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Widgets/SViewport.h"
#include <atomic>
#include <emscripten/em_js.h>
#include <emscripten/proxying.h>
#include <emscripten/threading.h>

namespace
{
constexpr int32 MailboxSize = 65536;
alignas(4) char Mailbox[MailboxSize];
std::atomic<int32> MailboxFull {0};
TMap<int32, TWeakPtr<SGHSWasmBrowser>> Browsers;
int32 NextId = 0;

// Like the engine's page command channel, this never synchronously waits on the browser main thread.
// The static mailbox outlives every widget, including callbacks during level travel.
EM_JS(void, InstallHud, (double BufferOffset, double FlagOffset, int Size), {
    if (globalThis.ghsWasmHUD) return;
    const frames = new Map(), queue = [], encoder = new TextEncoder();
    let serial = 0;
    function enqueue(message) {
        if (queue.length >= 128) return false;
        if (encoder.encode(JSON.stringify(message)).length > Size - 8) return false;
        queue.push(message); return true;
    }
    function drain() {
        const flag = new Int32Array(HEAP8.buffer, FlagOffset, 1);
        if (!queue.length || Atomics.load(flag, 0)) return;
        const batch = [];
        while (queue.length && encoder.encode(JSON.stringify(batch.concat([queue[0]]))).length < Size - 1) batch.push(queue.shift());
        const bytes = encoder.encode(JSON.stringify(batch));
        const target = new Uint8Array(HEAP8.buffer, BufferOffset, Size);
        target.set(bytes); target[bytes.length] = 0;
        Atomics.store(flag, 0, 1);
    }
    function bind(id, child) {
        const frame = frames.get(id);
        if (!frame || child !== frame.iframe.contentWindow) return;
        function request(method, value) {
            const request = ++serial;
            return new Promise((resolve, reject) => {
                if (!enqueue({id, request, method, value: String(value || "")})) { reject(new Error('HUD command queue full')); return; }
                const timeout = setTimeout(() => { frame.pending.delete(request); reject(new Error('HUD response timed out')); }, 15000);
                frame.pending.set(request, {resolve, reject, timeout});
            });
        }
        child.ue = {twin: {
            command: value => {
                // Fullscreen must retain this browser click's user activation, before the worker queue.
                // Fullscreen the whole document so both the canvas and its DOM HUD remain visible.
                try {
                    if (JSON.parse(value).action === 'fullscreen')
                        return document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
                } catch (error) { return Promise.reject(error); }
                return request('command', value);
            }, getstate: () => request('getstate'),
            getsnapshot: () => request('getsnapshot'), getscenecontrolsstate: () => request('getscenecontrolsstate'),
            getreplaystate: () => request('getreplaystate')
        }};
    }
    function run(frame, script) {
        try { frame.iframe.contentWindow.eval(script); }
        catch (error) { console.error('GHS_WEB_HUD script failed', error); }
    }
    function apply(message) {
        const id = message.id;
        if (message.op === 'create') {
            if (frames.has(id)) return;
            const wrapper = document.createElement('div'), iframe = document.createElement('iframe');
            wrapper.style.cssText = 'position:fixed;overflow:hidden;display:none;z-index:2;pointer-events:auto';
            iframe.style.cssText = 'position:absolute;border:0;display:block;background:transparent';
            iframe.title = 'GHS 仓库交互界面'; iframe.setAttribute('allow', 'cross-origin-isolated; fullscreen');
            wrapper.appendChild(iframe); document.body.appendChild(wrapper);
            const frame = {wrapper, iframe, pending:new Map(), scripts:[], loaded:false}; frames.set(id, frame);
            iframe.addEventListener('load', () => {
                if (!iframe.contentWindow.ue) return;
                frame.loaded = true; frame.scripts.splice(0).forEach(script => run(frame, script));
            });
            const url = new URL(message.url, document.baseURI);
            fetch(url).then(response => { if (!response.ok) throw new Error('HTTP ' + response.status); return response.text(); }).then(html => {
                if (frames.get(id) !== frame) return;
                const base = new URL('.', url).href.split('&').join('&amp;').split(String.fromCharCode(34)).join('&quot;');
                const bridge = '<base href="' + base + '"><script>parent.ghsWasmHUD.bind(' + id + ',window);<\/script>';
                iframe.srcdoc = html.replace(/<head([^>]*)>/i, '<head$1>' + bridge);
            }).catch(error => { console.error('UE_RUN ERROR GHS_WEB_HUD_LOAD', message.url, error); });
            return;
        }
        const frame = frames.get(id); if (!frame) return;
        if (message.op === 'remove') {
            for (const pending of frame.pending.values()) { clearTimeout(pending.timeout); pending.reject(new Error('HUD closed')); }
            frame.wrapper.remove(); frames.delete(id); return;
        }
        if (message.op === 'eval') {
            if (frame.loaded) run(frame, message.script);
            else if (frame.scripts.length < 128) frame.scripts.push(message.script);
            return;
        }
        if (message.op === 'reply') {
            const pending = frame.pending.get(message.request); if (!pending) return;
            clearTimeout(pending.timeout); frame.pending.delete(message.request);
            if (message.error) pending.reject(new Error(message.error)); else pending.resolve(message.value);
            return;
        }
        if (message.op === 'layout') {
            const canvas = document.querySelector('canvas'), rect = canvas && canvas.getBoundingClientRect();
            if (!rect || !message.visible || !message.vw || !message.vh) { frame.wrapper.style.display = 'none'; return; }
            const sx = rect.width / message.vw, sy = rect.height / message.vh;
            const left = Math.max(message.x, message.cl), top = Math.max(message.y, message.ct);
            const right = Math.min(message.x + message.w, message.cr), bottom = Math.min(message.y + message.h, message.cb);
            const style = frame.wrapper.style;
            style.display = right > left && bottom > top ? 'block' : 'none';
            style.left = rect.left + left * sx + 'px'; style.top = rect.top + top * sy + 'px';
            style.width = Math.max(0, right - left) * sx + 'px'; style.height = Math.max(0, bottom - top) * sy + 'px';
            style.opacity = message.opacity;
            const inner = frame.iframe.style;
            inner.left = (message.x - left) * sx + 'px'; inner.top = (message.y - top) * sy + 'px';
            inner.width = message.w * sx + 'px'; inner.height = message.h * sy + 'px';
        }
    }
    globalThis.ghsWasmHUD = {bind, apply};
    setInterval(drain, 16);
});

EM_JS(void, ApplyHud, (const char* Payload), {
    // wasm64 passes C pointers as BigInt; Emscripten's string reader indexes the heap with Number.
    if (globalThis.ghsWasmHUD) globalThis.ghsWasmHUD.apply(JSON.parse(UTF8ToString(Number(Payload))));
});

void Send(const TSharedRef<FJsonObject>& Object)
{
    FString Json; FJsonSerializer::Serialize(Object, TJsonWriterFactory<>::Create(&Json));
    auto* Payload = new FTCHARToUTF8(*Json);
    const int Queued = emscripten_proxy_async(emscripten_proxy_get_system_queue(), emscripten_main_runtime_thread_id(),
        [](void* Data) { auto* Text = static_cast<FTCHARToUTF8*>(Data); ApplyHud(reinterpret_cast<const char*>(Text->Get())); delete Text; }, Payload);
    if (!Queued) delete Payload;
}

TSharedRef<FJsonObject> Message(const TCHAR* Operation, int32 Id)
{
    auto Result = MakeShared<FJsonObject>(); Result->SetStringField(TEXT("op"), Operation); Result->SetNumberField(TEXT("id"), Id); return Result;
}
}

void SGHSWasmBrowser::Construct(const FArguments& Args)
{
    static bool Installed = false;
    if (!Installed)
    {
        Installed = true;
        emscripten_proxy_async(emscripten_proxy_get_system_queue(), emscripten_main_runtime_thread_id(),
            [](void*) { InstallHud(double(UPTRINT(Mailbox)), double(UPTRINT(&MailboxFull)), MailboxSize); }, nullptr);
        FCoreDelegates::OnEndFrame.AddStatic(&SGHSWasmBrowser::EndFrame);
    }
    Id = ++NextId; Browsers.Add(Id, StaticCastSharedRef<SGHSWasmBrowser>(AsShared()));
    ForceVolatile(true);
    const FString Document = Args._Document;
    check(Document == TEXT("index.html") || Document == TEXT("globe.html") || Document == TEXT("replay-overlay.html"));
    auto Create = Message(TEXT("create"), Id);
    Create->SetStringField(TEXT("url"), FString(FApp::GetProjectName()) / TEXT("Content/GHSTwinUI/web") / Document);
    Send(Create);
}

SGHSWasmBrowser::~SGHSWasmBrowser() { Browsers.Remove(Id); Send(Message(TEXT("remove"), Id)); }
void SGHSWasmBrowser::Bind(UObject* Target) { BoundTarget = Target; }
void SGHSWasmBrowser::Evaluate(const FString& Script)
{
    auto Update = Message(TEXT("eval"), Id); Update->SetStringField(TEXT("script"), Script); Send(Update);
}

int32 SGHSWasmBrowser::OnPaint(const FPaintArgs&, const FGeometry& Geometry, const FSlateRect& Clip,
    FSlateWindowElementList&, int32 LayerId, const FWidgetStyle& Style, bool) const
{
    if (!GEngine || !GEngine->GameViewport || !GEngine->GameViewport->GetGameViewportWidget()) return LayerId;
    const auto& View = GEngine->GameViewport->GetGameViewportWidget()->GetCachedGeometry();
    const FVector2D Origin = View.AbsoluteToLocal(Geometry.LocalToAbsolute(FVector2D::ZeroVector));
    const FVector2D End = View.AbsoluteToLocal(Geometry.LocalToAbsolute(Geometry.GetLocalSize()));
    const FVector2D ClipStart = View.AbsoluteToLocal(FVector2D(Clip.Left, Clip.Top));
    const FVector2D ClipEnd = View.AbsoluteToLocal(FVector2D(Clip.Right, Clip.Bottom));
    Layout = Message(TEXT("layout"), Id); LastPaintFrame = GFrameCounter;
    Layout->SetNumberField(TEXT("x"), Origin.X); Layout->SetNumberField(TEXT("y"), Origin.Y);
    Layout->SetNumberField(TEXT("w"), End.X - Origin.X); Layout->SetNumberField(TEXT("h"), End.Y - Origin.Y);
    Layout->SetNumberField(TEXT("cl"), ClipStart.X); Layout->SetNumberField(TEXT("ct"), ClipStart.Y);
    Layout->SetNumberField(TEXT("cr"), ClipEnd.X); Layout->SetNumberField(TEXT("cb"), ClipEnd.Y);
    Layout->SetNumberField(TEXT("vw"), View.GetLocalSize().X); Layout->SetNumberField(TEXT("vh"), View.GetLocalSize().Y);
    Layout->SetNumberField(TEXT("opacity"), Style.GetColorAndOpacityTint().A * GetRenderOpacity());
    return LayerId;
}

void SGHSWasmBrowser::EndFrame()
{
    if (MailboxFull.load(std::memory_order_acquire))
    {
        const FString Json = UTF8_TO_TCHAR(Mailbox);
        MailboxFull.store(0, std::memory_order_release);
        TArray<TSharedPtr<FJsonValue>> Messages;
        if (FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Messages))
            for (const auto& Value : Messages)
            {
                const auto Object = Value->AsObject(); double BrowserId = 0;
                if (!Object || !Object->TryGetNumberField(TEXT("id"), BrowserId)) continue;
                const auto* Found = Browsers.Find(int32(BrowserId));
                if (Found) if (const auto Browser = Found->Pin()) Browser->Receive(Object);
            }
    }
    for (const auto& Pair : Browsers)
        if (const auto Browser = Pair.Value.Pin(); Browser && Browser->Layout)
        {
            Browser->Layout->SetBoolField(TEXT("visible"), Browser->LastPaintFrame != MAX_uint64 && GFrameCounter <= Browser->LastPaintFrame + 1);
            Send(Browser->Layout.ToSharedRef());
        }
}

void SGHSWasmBrowser::Receive(const TSharedPtr<FJsonObject>& Object)
{
    FString Method, Value; double Request = 0;
    if (!Object->TryGetStringField(TEXT("method"), Method) || !Object->TryGetNumberField(TEXT("request"), Request)) return;
    Object->TryGetStringField(TEXT("value"), Value);
    auto Reply = Message(TEXT("reply"), Id); Reply->SetNumberField(TEXT("request"), Request);
    FString Result; bool Handled = false;
    if (Value.Len() <= 32768)
    {
        if (auto* Twin = Cast<UGHSTwinHUDWidget>(BoundTarget.Get()))
        {
            if (Method == TEXT("command")) { Twin->Command(Value); Handled = true; }
            else if (Method == TEXT("getsnapshot")) { Result = Twin->GetSnapshot(); Handled = true; }
            else if (Method == TEXT("getscenecontrolsstate")) { Result = Twin->GetSceneControlsState(); Handled = true; }
            else if (Method == TEXT("getreplaystate")) { Result = Twin->GetReplayState(); Handled = true; }
        }
        else if (auto* Globe = Cast<AGHSGlobePlayerController>(BoundTarget.Get()))
        {
            if (Method == TEXT("command")) { Globe->Command(Value); Handled = true; }
            else if (Method == TEXT("getstate")) { Result = Globe->GetState(); Handled = true; }
        }
    }
    if (Handled) Reply->SetStringField(TEXT("value"), Result);
    else Reply->SetStringField(TEXT("error"), TEXT("HUD binding or method unavailable"));
    Send(Reply);
}
#endif
