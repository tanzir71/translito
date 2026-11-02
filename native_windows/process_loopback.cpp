// Translito process-loopback bridge. No file output, endpoint or policy changes.
// API reference: Microsoft's ApplicationLoopback sample (MIT).
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <audiopolicy.h>
#include <endpointvolume.h>
#include <mmdeviceapi.h>
#include <wrl.h>
#include <set>
#include <algorithm>

using namespace Microsoft::WRL;
using PcmCallback = void (*)(const short*, unsigned, void*);
#define EXPORT extern "C" __declspec(dllexport)
#define CHECK_HR(call) do { HRESULT hr = (call); if (FAILED(hr)) return hr; } while (0)

class Handle {
public:
    HANDLE value;
    explicit Handle(bool manual = false) : value(CreateEventW(nullptr, manual, FALSE, nullptr)) {}
    ~Handle() { if (value) CloseHandle(value); }
    Handle(const Handle&) = delete;
};

class Activation final : public RuntimeClass<RuntimeClassFlags<ClassicCom>,
    IActivateAudioInterfaceCompletionHandler, FtmBase> {
public:
    Handle done;
    HRESULT result = E_PENDING;
    ComPtr<IAudioClient> client;
    AUDIOCLIENT_ACTIVATION_PARAMS parameters = {};
    PROPVARIANT blob = {};
    STDMETHOD(ActivateCompleted)(IActivateAudioInterfaceAsyncOperation* operation) override {
        HRESULT activated = E_FAIL;
        ComPtr<IUnknown> unknown;
        result = operation->GetActivateResult(&activated, &unknown);
        if (SUCCEEDED(result)) result = activated;
        if (SUCCEEDED(result)) result = unknown.As(&client);
        SetEvent(done.value);
        return S_OK;
    }
};

static HRESULT Capture(DWORD pid, bool exclude, HANDLE stop, PcmCallback callback, void* context) {
    auto activation = Make<Activation>();
    if (!activation || !activation->done.value) return E_OUTOFMEMORY;
    activation->parameters.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
    activation->parameters.ProcessLoopbackParams.TargetProcessId = pid;
    activation->parameters.ProcessLoopbackParams.ProcessLoopbackMode = exclude
        ? PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE
        : PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;
    activation->blob.vt = VT_BLOB;
    activation->blob.blob.cbSize = sizeof(activation->parameters);
    activation->blob.blob.pBlobData = reinterpret_cast<BYTE*>(&activation->parameters);
    ComPtr<IActivateAudioInterfaceAsyncOperation> operation;
    CHECK_HR(ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
        __uuidof(IAudioClient), &activation->blob, activation.Get(), &operation));
    HANDLE activationEvents[] = {stop, activation->done.value};
    DWORD wait = WaitForMultipleObjects(2, activationEvents, FALSE, 5000);
    if (wait == WAIT_OBJECT_0) return S_OK;
    if (wait != WAIT_OBJECT_0 + 1) return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
    CHECK_HR(activation->result);
    auto client = activation->client;
    WAVEFORMATEX format = {};
    format.wFormatTag = WAVE_FORMAT_PCM;
    format.nChannels = 2;
    format.nSamplesPerSec = 48000;
    format.wBitsPerSample = 16;
    format.nBlockAlign = 4;
    format.nAvgBytesPerSec = 192000;
    CHECK_HR(client->Initialize(AUDCLNT_SHAREMODE_SHARED,
        AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK |
        AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM, 0, 0, &format, nullptr));
    ComPtr<IAudioCaptureClient> reader;
    CHECK_HR(client->GetService(IID_PPV_ARGS(&reader)));
    Handle samples;
    if (!samples.value) return E_OUTOFMEMORY;
    CHECK_HR(client->SetEventHandle(samples.value));
    CHECK_HR(client->Start());
    callback(nullptr, 0, context); // Ready; nonzero frames below are stereo PCM16.
    HRESULT result = S_OK;
    HANDLE events[] = {stop, samples.value};
    while (WaitForSingleObject(stop, 0) == WAIT_TIMEOUT) {
        wait = WaitForMultipleObjects(2, events, FALSE, 100);
        if (wait == WAIT_OBJECT_0) break;
        if (wait == WAIT_TIMEOUT) continue;
        if (wait != WAIT_OBJECT_0 + 1) { result = E_FAIL; break; }
        UINT32 count = 0;
        result = reader->GetNextPacketSize(&count);
        if (FAILED(result)) break;
        while (count && WaitForSingleObject(stop, 0) == WAIT_TIMEOUT) {
            BYTE* data = nullptr;
            DWORD flags = 0;
            UINT32 frames = 0;
            result = reader->GetBuffer(&data, &frames, &flags, nullptr, nullptr);
            if (FAILED(result)) break;
            callback((flags & AUDCLNT_BUFFERFLAGS_SILENT) ? nullptr : reinterpret_cast<short*>(data), frames, context);
            result = reader->ReleaseBuffer(frames);
            if (FAILED(result)) break;
            result = reader->GetNextPacketSize(&count);
            if (FAILED(result)) break;
        }
        if (FAILED(result)) break;
    }
    client->Stop();
    return result;
}

EXPORT unsigned translito_capture_abi() { return 1; }

EXPORT HRESULT translito_capture_run(DWORD pid, BOOL exclude, HANDLE stop, PcmCallback callback, void* context) {
    if (!pid || !stop || !callback) return E_INVALIDARG;
    HRESULT init = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(init)) return init;
    HRESULT result = E_FAIL;
    try { result = Capture(pid, exclude != FALSE, stop, callback, context); }
    catch (...) { result = E_OUTOFMEMORY; }
    CoUninitialize();
    return result;
}

static HRESULT Enumerate(DWORD* pids, unsigned capacity, unsigned* count) {
    ComPtr<IMMDeviceEnumerator> enumerator;
    CHECK_HR(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, IID_PPV_ARGS(&enumerator)));
    ComPtr<IMMDeviceCollection> endpoints;
    CHECK_HR(enumerator->EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE, &endpoints));
    UINT endpointCount = 0;
    CHECK_HR(endpoints->GetCount(&endpointCount));
    std::set<DWORD> active;
    for (UINT i = 0; i < endpointCount; ++i) {
        ComPtr<IMMDevice> endpoint;
        ComPtr<IAudioSessionManager2> manager;
        ComPtr<IAudioSessionEnumerator> sessions;
        if (FAILED(endpoints->Item(i, &endpoint)) ||
            FAILED(endpoint->Activate(__uuidof(IAudioSessionManager2), CLSCTX_ALL, nullptr,
                reinterpret_cast<void**>(manager.GetAddressOf()))) ||
            FAILED(manager->GetSessionEnumerator(&sessions))) continue;
        int sessionCount = 0;
        if (FAILED(sessions->GetCount(&sessionCount))) continue;
        for (int j = 0; j < sessionCount; ++j) {
            ComPtr<IAudioSessionControl> control;
            ComPtr<IAudioSessionControl2> process;
            ComPtr<IAudioMeterInformation> meter;
            AudioSessionState state;
            DWORD pid = 0;
            float peak = 0;
            if (FAILED(sessions->GetSession(j, &control)) ||
                FAILED(control->GetState(&state)) || state != AudioSessionStateActive ||
                FAILED(control.As(&process)) || FAILED(process->GetProcessId(&pid)) || !pid ||
                FAILED(control.As(&meter)) || FAILED(meter->GetPeakValue(&peak)) || peak <= 1e-7f) continue;
            active.insert(pid);
        }
    }
    *count = (std::min)(capacity, static_cast<unsigned>(active.size()));
    std::copy_n(active.begin(), *count, pids);
    return S_OK;
}

EXPORT HRESULT translito_capture_processes(DWORD* pids, unsigned capacity, unsigned* count) {
    if (!pids || !capacity || !count) return E_INVALIDARG;
    *count = 0;
    HRESULT init = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(init) && init != RPC_E_CHANGED_MODE) return init;
    HRESULT result = E_FAIL;
    try { result = Enumerate(pids, capacity, count); }
    catch (...) { result = E_OUTOFMEMORY; }
    if (SUCCEEDED(init)) CoUninitialize();
    return result;
}
