const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('liac', {
    start: () => ipcRenderer.invoke('hub:start'),
    submit: (id, text) => ipcRenderer.invoke('hub:submit', id, text),
    voiceSettings: () => ipcRenderer.invoke('hub:voice-settings'),
    configureVoice: draft => ipcRenderer.invoke('hub:configure-voice', draft),
    previewVoice: draft => ipcRenderer.invoke('hub:preview-voice', draft),
    synthesize: text => ipcRenderer.invoke('hub:synthesize', text),
    cancelVoice: () => ipcRenderer.invoke('hub:cancel-voice'),
    recordContext: enabled => ipcRenderer.invoke('hub:context', enabled),
    runs: () => ipcRenderer.invoke('hub:runs'),
    replay: (id, token) => ipcRenderer.invoke('hub:replay', id, token),
    resume: id => ipcRenderer.invoke('hub:resume', id),
    onFrame: callback => ipcRenderer.on('hub:frame', (_event, stream, frame) => callback(stream, frame)),
});
