// Start-up, once every editor script has loaded.
'use strict';
S.supers = S.supers || [];
S.selWords = new Set();
initHits();
initSupers();
$('addTextBtn').onclick = addSuper;
$('railText').onclick = addSuper;
inspectorSync();
loadRecent();
// /app?p=<id> reopens a project (also after a reload)
const openPid = new URLSearchParams(location.search).get('p');
if (openPid) openProjectById(openPid);
initEngine();
initClips();
initCut();
