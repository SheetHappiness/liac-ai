const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('liac', {
    start: () => ipcRenderer.invoke('hub:start'),
    submit: (id, text) => ipcRenderer.invoke('hub:submit', id, text),
    recordContext: enabled => ipcRenderer.invoke('hub:context', enabled),
    runs: () => ipcRenderer.invoke('hub:runs'),
    replay: (id, token) => ipcRenderer.invoke('hub:replay', id, token),
    onFrame: callback => ipcRenderer.on('hub:frame', (_event, stream, frame) => callback(stream, frame)),
});
