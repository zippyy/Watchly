// Accounts page state + Watch History Source segmented control on Configure.
//
// Each provider card has two views — disconnected (login UI) and connected
// (status + Disconnect) — toggled via setProviderConnected. The Configure
// page's source picker is always interactive: clicking a provider that isn't
// connected jumps the user to the matching card in Accounts instead of
// silently doing nothing.

import { showToast } from './ui.js';
import { unlockNavigation } from './navigation.js';

const ACTIVE_CLASSES = ['bg-white/10', 'text-white', 'shadow-sm'];
const ACTIVE_BORDER_CLASS = 'border-white/20';
const INACTIVE_CLASSES = ['text-slate-400', 'hover:text-white', 'hover:bg-white/5'];
const INACTIVE_BORDER_CLASS = 'border-transparent';

const SOURCE_ORDER = ['stremio', 'trakt', 'simkl', 'nuvio'];
const PROVIDER_LABELS = { stremio: 'Stremio', trakt: 'Trakt', simkl: 'Simkl', nuvio: 'Nuvio' };

let switchSectionFn = null;
const connectedState = { stremio: false, trakt: false, simkl: false, nuvio: false };
let selectedSources = new Set(['stremio']);

export function initializeAccountsUI({ switchSection } = {}) {
    switchSectionFn = switchSection || null;

    document.querySelectorAll('.source-btn').forEach(btn => {
        btn.addEventListener('click', () => onSourceButtonClick(btn.dataset.sourceBtn));
    });

    document.querySelectorAll('.account-link').forEach(link => {
        link.addEventListener('click', () => goToAccounts());
    });

    syncSourceInputs();
    syncAccountsNextButton();
}

export function setStremioConnected(connected) {
    connectedState.stremio = connected;
    setProviderDot('stremio', connected);
    setProviderView('stremio', connected);

    if (connected) {
        selectedSources.add('stremio');
    } else {
        selectedSources.delete('stremio');
        ensureAtLeastOneConnectedSource();
    }

    syncSourceInputs();
    syncAccountsNextButton();
}

export function setProviderConnected(provider, connected) {
    if (provider === 'stremio') {
        setStremioConnected(connected);
        return;
    }
    if (!['trakt', 'simkl', 'nuvio'].includes(provider)) return;

    connectedState[provider] = connected;
    setProviderDot(provider, connected);
    setProviderView(provider, connected);

    if (connected) {
        unlockNavigation();
        selectedSources.add(provider);
        if (!connectedState.stremio) selectedSources.delete('stremio');
    } else {
        selectedSources.delete(provider);
        ensureAtLeastOneConnectedSource();
    }

    syncSourceInputs();
    syncAccountsNextButton();
}

function ensureAtLeastOneConnectedSource() {
    if (selectedSources.size > 0) return;
    const fallback = firstConnectedSource();
    if (fallback) selectedSources.add(fallback);
}

function firstConnectedSource() {
    return SOURCE_ORDER.find(source => connectedState[source]) || null;
}

export function getWatchHistorySources() {
    return SOURCE_ORDER.filter(source => selectedSources.has(source));
}

export function setWatchHistorySources(values) {
    const requested = Array.isArray(values) ? values : [];
    selectedSources = new Set(SOURCE_ORDER.filter(source => requested.includes(source)));
    syncSourceInputs();
}

export function setWatchHistorySource(value) {
    setWatchHistorySources(value ? [value] : []);
}

function syncSourceInputs() {
    const sources = getWatchHistorySources();
    const hiddenSources = document.getElementById('watchHistorySources');
    const hiddenLegacy = document.getElementById('watchHistorySource');
    if (hiddenSources) hiddenSources.value = sources.join(',');
    if (hiddenLegacy) hiddenLegacy.value = sources[0] || '';

    document.querySelectorAll('.source-btn').forEach(btn => {
        const active = selectedSources.has(btn.dataset.sourceBtn);
        applyActive(btn, active);
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
}

function onSourceButtonClick(provider) {
    if (!connectedState[provider]) {
        showToast('Connect ' + PROVIDER_LABELS[provider] + ' in Accounts to use its watch history.', 'info', 4000);
        goToAccounts(provider);
        return;
    }

    if (selectedSources.has(provider)) {
        selectedSources.delete(provider);
    } else {
        selectedSources.add(provider);
    }
    syncSourceInputs();
}

function goToAccounts(scrollTo) {
    if (typeof switchSectionFn === 'function') {
        switchSectionFn('login');
    }
    if (scrollTo) {
        // Defer until the section is visible after switchSection completes.
        requestAnimationFrame(() => {
            const target = document.getElementById(`provider-${scrollTo}`);
            if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    }
}

function syncAccountsNextButton() {
    const btn = document.getElementById('accountsNextBtn');
    if (!btn) return;
    btn.disabled = !(connectedState.stremio || connectedState.trakt || connectedState.simkl || connectedState.nuvio);
}

function setProviderView(provider, connected) {
    const disconnected = document.querySelector(`[data-provider-view="disconnected"][data-provider-for="${provider}"]`);
    const connectedEl = document.querySelector(`[data-provider-view="connected"][data-provider-for="${provider}"]`);
    if (disconnected) disconnected.classList.toggle('hidden', connected);
    if (connectedEl) connectedEl.classList.toggle('hidden', !connected);
}

function applyActive(btn, isActive) {
    btn.classList.remove(...ACTIVE_CLASSES, ...INACTIVE_CLASSES, ACTIVE_BORDER_CLASS, INACTIVE_BORDER_CLASS);
    if (isActive) {
        btn.classList.add(...ACTIVE_CLASSES, ACTIVE_BORDER_CLASS);
    } else {
        btn.classList.add(...INACTIVE_CLASSES, INACTIVE_BORDER_CLASS);
    }
}

function setProviderDot(provider, connected) {
    const badge = document.querySelector(`[data-account-dot="${provider}"]`);
    if (badge) {
        badge.textContent = connected ? 'Connected' : 'Not connected';
        badge.classList.toggle('bg-green-500/15', connected);
        badge.classList.toggle('text-green-300', connected);
        badge.classList.toggle('border-green-400/20', connected);
        badge.classList.toggle('bg-red-500/15', !connected);
        badge.classList.toggle('text-red-300', !connected);
        badge.classList.toggle('border-red-400/20', !connected);
    }

    const pip = document.querySelector(`[data-source-pip="${provider}"]`);
    if (pip) {
        pip.classList.toggle('bg-green-400', connected);
        pip.classList.toggle('bg-slate-600', !connected);
    }
}
