// "Install on Nuvio" — writes the addon into the user's Nuvio Sync account.
//
// Nuvio has no install deep link, but its apps sync installed addons from a
// Supabase table. We sign the user in with their Nuvio credentials directly
// from the browser (same approach as the community Trakt-Nuvio bridge) and
// insert the addon row. Credentials and tokens never touch Watchly's servers.
//
// This rides on Nuvio's unofficial API: failures are expected eventually, so
// every error path falls back to "copy the URL and paste it in Nuvio".

const NUVIO_BASE = 'https://dpyhjjcoabcglfmgecug.supabase.co';
// Public (publishable) client key, same one Nuvio's own web app ships.
const NUVIO_KEY = 'sb_publishable_zcNkgqGJjBtj8GoRlMvl9A_zkdmXhf5';

const FALLBACK_HINT = 'You can always install manually: copy the manifest URL, then in Nuvio go to Settings → Addons and paste it.';

async function nuvioRequest(path, { method = 'GET', token, body, headers = {} } = {}) {
    const response = await fetch(`${NUVIO_BASE}${path}`, {
        method,
        headers: {
            apikey: NUVIO_KEY,
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
            ...headers,
        },
        body: body === undefined ? undefined : JSON.stringify(body),
    });

    let data = null;
    try {
        data = await response.json();
    } catch (e) { /* empty body (e.g. 201 with return=minimal) */ }

    if (!response.ok) {
        const message = data?.error_description || data?.msg || data?.message || `Nuvio request failed (${response.status})`;
        throw new Error(message);
    }
    return data;
}

async function nuvioLogin(email, password) {
    const data = await nuvioRequest('/auth/v1/token?grant_type=password', {
        method: 'POST',
        body: { email, password },
    });
    if (!data?.access_token || !data?.user?.id) {
        throw new Error('Nuvio did not return a session. Check your credentials.');
    }
    return { token: data.access_token, userId: data.user.id };
}

async function nuvioProfiles(token) {
    const profiles = await nuvioRequest('/rest/v1/rpc/sync_pull_profiles', { method: 'POST', token, body: {} });
    return Array.isArray(profiles) && profiles.length ? profiles : [{ profile_index: 1, name: 'Default' }];
}

async function installToProfile({ token, userId, profileId, manifestUrl, legacyManifestUrl }) {
    const params = `select=id,url,sort_order&user_id=eq.${encodeURIComponent(userId)}&profile_id=eq.${profileId}`;
    const existing = await nuvioRequest(`/rest/v1/addons?${params}`, { token });
    const rows = Array.isArray(existing) ? existing : [];

    if (rows.some(row => row.url === manifestUrl)) {
        return 'already-installed';
    }

    const legacy = legacyManifestUrl ? rows.find(row => row.url === legacyManifestUrl && row.id) : null;
    if (legacy) {
        await nuvioRequest(
            `/rest/v1/addons?id=eq.${encodeURIComponent(legacy.id)}&user_id=eq.${encodeURIComponent(userId)}&profile_id=eq.${profileId}`,
            {
                method: 'PATCH',
                token,
                headers: { Prefer: 'return=minimal' },
                body: {
                    url: manifestUrl,
                    name: 'Watchly',
                    enabled: true,
                },
            }
        );
        return 'updated';
    }

    const sortOrder = rows.reduce((max, row) => Math.max(max, Number(row.sort_order) || 0), 0) + 1;
    await nuvioRequest('/rest/v1/addons', {
        method: 'POST',
        token,
        headers: { Prefer: 'return=minimal' },
        body: {
            user_id: userId,
            profile_id: profileId,
            url: manifestUrl,
            name: 'Watchly',
            enabled: true,
            sort_order: sortOrder,
        },
    });
    return 'installed';
}

const NUVIO_ORIGIN_STORAGE_KEY = 'watchly:nuvio-origin-client-id';

function nuvioOriginClientId() {
    try {
        const existing = localStorage.getItem(NUVIO_ORIGIN_STORAGE_KEY);
        if (existing && /^[A-Za-z0-9_-]{16,96}$/.test(existing)) {
            return existing;
        }
    } catch (e) { /* localStorage can be unavailable in hardened browsers */ }

    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    const suffix = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
    const generated = `watchly-web-${suffix}`;

    try {
        localStorage.setItem(NUVIO_ORIGIN_STORAGE_KEY, generated);
    } catch (e) { /* an ephemeral id is still accepted by Nuvio */ }

    return generated;
}

function nuvioManifestUrlFromManifest(manifestUrl) {
    const url = new URL(manifestUrl, window.location.href);
    if (!url.pathname.endsWith('/manifest.json')) {
        throw new Error('Unable to derive the Nuvio manifest URL from this manifest.');
    }
    url.pathname = url.pathname.replace(/\/manifest\.json$/, '/nuvio/manifest.json');
    url.search = '';
    url.hash = '';
    return url.toString();
}

function collectionUrlFromManifest(manifestUrl) {
    const url = new URL(manifestUrl, window.location.href);
    if (!url.pathname.endsWith('/manifest.json')) {
        throw new Error('Unable to derive the Nuvio Collection URL from this manifest.');
    }
    url.pathname = url.pathname.replace(/\/manifest\.json$/, '/nuvio-collection.json');
    url.search = '';
    url.hash = '';
    return url.toString();
}

async function fetchWatchlyCollection(manifestUrl) {
    const response = await fetch(collectionUrlFromManifest(manifestUrl), {
        headers: { Accept: 'application/json' },
    });
    if (!response.ok) {
        throw new Error(`Watchly collection request failed (${response.status})`);
    }
    const collection = await response.json();
    if (!collection?.id || !Array.isArray(collection?.folders)) {
        throw new Error('Watchly returned an invalid Nuvio Collection.');
    }
    return collection;
}

async function nuvioCollections(token, profileId) {
    const rows = await nuvioRequest('/rest/v1/rpc/sync_pull_collections', {
        method: 'POST',
        token,
        body: { p_profile_id: profileId },
    });

    const blob = Array.isArray(rows) ? rows[0] : rows;
    const value = blob?.collections_json;
    if (Array.isArray(value)) return value;

    if (typeof value === 'string' && value.trim()) {
        try {
            const parsed = JSON.parse(value);
            return Array.isArray(parsed) ? parsed : [];
        } catch (e) {
            throw new Error('Nuvio returned malformed collection data.');
        }
    }

    return [];
}

function mergeWatchlyCollection(existing, collection) {
    const merged = Array.isArray(existing) ? [...existing] : [];
    const index = merged.findIndex(item => item?.id === collection.id);
    if (index >= 0) {
        merged[index] = collection;
    } else {
        merged.unshift(collection);
    }
    return merged;
}

async function pushNuvioCollections({ token, profileId, collections }) {
    await nuvioRequest('/rest/v1/rpc/sync_push_collections', {
        method: 'POST',
        token,
        body: {
            p_profile_id: profileId,
            p_collections_json: collections,
            p_origin_client_id: nuvioOriginClientId(),
        },
    });
}

async function installCollectionToProfile({ token, profileId, manifestUrl }) {
    const [existing, collection] = await Promise.all([
        nuvioCollections(token, profileId),
        fetchWatchlyCollection(manifestUrl),
    ]);
    const merged = mergeWatchlyCollection(existing, collection);
    await pushNuvioCollections({ token, profileId, collections: merged });
    return existing.some(item => item?.id === collection.id) ? 'updated' : 'created';
}

// --- Modal UI ---

let modalEl = null;

function ensureModal() {
    if (modalEl) return modalEl;

    modalEl = document.createElement('div');
    modalEl.id = 'nuvioInstallModal';
    modalEl.className = 'fixed inset-0 z-50 hidden items-center justify-center p-4';
    modalEl.innerHTML = `
        <div class="absolute inset-0 bg-black/70 backdrop-blur-sm" data-nuvio-close></div>
        <div class="relative bg-neutral-900 border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl shadow-black/50">
            <div class="flex items-start justify-between mb-1">
                <h3 class="text-lg font-semibold text-white">Install on Nuvio</h3>
                <button type="button" class="text-slate-500 hover:text-white transition" data-nuvio-close aria-label="Close">✕</button>
            </div>
            <p class="text-xs text-slate-500 mb-2">This signs you in to <strong class="text-slate-400">Nuvio</strong>,
                not Watchly. Your Nuvio email and password go straight from this page to Nuvio's own servers &mdash;
                Watchly never receives, stores or logs them.</p>
            <p class="text-xs text-slate-500 mb-5">Prefer not to type them here? Close this and use
                <strong class="text-slate-400">Copy Link</strong> instead, then paste the URL into Nuvio under
                Settings &rarr; Addons.</p>

            <div id="nuvioLoginStep" class="grid gap-3">
                <input id="nuvioEmail" type="email" autocomplete="off" placeholder="Nuvio email"
                    class="w-full bg-neutral-950 border border-slate-700 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:ring-2 focus:ring-white/20 focus:border-white/30 outline-none transition-all">
                <input id="nuvioPassword" type="password" autocomplete="off" placeholder="Nuvio password"
                    class="w-full bg-neutral-950 border border-slate-700 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:ring-2 focus:ring-white/20 focus:border-white/30 outline-none transition-all">
                <button type="button" id="nuvioSubmitBtn"
                    class="mt-1 w-full bg-white text-black hover:bg-white/90 font-medium py-3 rounded-xl transition border border-white/10">
                    Sign in &amp; Install</button>
            </div>

            <div id="nuvioProfileStep" class="hidden grid gap-3">
                <label class="text-xs text-slate-400">Choose the profile to install to</label>
                <select id="nuvioProfileSelect"
                    class="w-full appearance-none bg-neutral-950 border border-slate-700 rounded-xl px-4 py-3 text-white outline-none"></select>
                <button type="button" id="nuvioProfileInstallBtn"
                    class="mt-1 w-full bg-white text-black hover:bg-white/90 font-medium py-3 rounded-xl transition border border-white/10">Install</button>
            </div>

            <div id="nuvioStatus" class="hidden mt-4 text-sm rounded-xl p-3"></div>
        </div>`;
    document.body.appendChild(modalEl);

    modalEl.querySelectorAll('[data-nuvio-close]').forEach(el => el.addEventListener('click', closeModal));
    return modalEl;
}

function closeModal() {
    if (!modalEl) return;
    modalEl.classList.add('hidden');
    modalEl.classList.remove('flex');
    const password = modalEl.querySelector('#nuvioPassword');
    if (password) password.value = '';
}

function setStatus(kind, message) {
    const el = modalEl.querySelector('#nuvioStatus');
    el.classList.remove('hidden', 'bg-red-500/10', 'text-red-200', 'bg-green-500/10', 'text-green-200', 'bg-white/5', 'text-slate-300');
    const styles = {
        error: ['bg-red-500/10', 'text-red-200'],
        success: ['bg-green-500/10', 'text-green-200'],
        info: ['bg-white/5', 'text-slate-300'],
    };
    el.classList.add(...styles[kind]);
    el.textContent = message;
}

function setBusy(button, busy, busyText) {
    button.disabled = busy;
    button.classList.toggle('opacity-60', busy);
    if (busy) {
        button.dataset.originalText = button.textContent;
        button.textContent = busyText;
    } else if (button.dataset.originalText) {
        button.textContent = button.dataset.originalText;
    }
}

export function openNuvioInstall(manifestUrl) {
    if (!manifestUrl) return;
    const modal = ensureModal();
    const nuvioManifestUrl = nuvioManifestUrlFromManifest(manifestUrl);

    const loginStep = modal.querySelector('#nuvioLoginStep');
    const profileStep = modal.querySelector('#nuvioProfileStep');
    const status = modal.querySelector('#nuvioStatus');
    loginStep.classList.remove('hidden');
    profileStep.classList.add('hidden');
    status.classList.add('hidden');

    let session = null;

    const finishInstall = async (profileId, button) => {
        setBusy(button, true, 'Installing…');
        let addonResult = null;
        try {
            addonResult = await installToProfile({
                ...session,
                profileId,
                manifestUrl: nuvioManifestUrl,
                legacyManifestUrl: manifestUrl,
            });
        } catch (err) {
            setStatus('error', `Addon install failed: ${err.message}. ${FALLBACK_HINT}`);
            setBusy(button, false);
            return;
        }

        try {
            setBusy(button, true, 'Creating For You…');
            const collectionResult = await installCollectionToProfile({
                token: session.token,
                profileId,
                manifestUrl,
            });
            loginStep.classList.add('hidden');
            profileStep.classList.add('hidden');

            const addonText = addonResult === 'already-installed'
                ? 'Watchly was already installed'
                : addonResult === 'updated'
                    ? 'Watchly was switched to Collection mode'
                    : 'Watchly was installed in Collection mode';
            const collectionText = collectionResult === 'updated'
                ? 'its For You collection was updated'
                : 'its For You collection was created';
            setStatus('success', `${addonText}, and ${collectionText}. Reopen Nuvio if it does not appear after the next sync.`);
        } catch (err) {
            loginStep.classList.add('hidden');
            profileStep.classList.add('hidden');
            setStatus(
                'error',
                `Watchly was installed, but the For You collection could not be synced: ${err.message}. You can retry Install on Nuvio safely; it will update rather than duplicate the collection.`
            );
        } finally {
            setBusy(button, false);
        }
    };

    const submitBtn = modal.querySelector('#nuvioSubmitBtn');
    submitBtn.onclick = async () => {
        const email = modal.querySelector('#nuvioEmail').value.trim();
        const password = modal.querySelector('#nuvioPassword').value;
        if (!email || !password) {
            setStatus('error', 'Enter your Nuvio email and password.');
            return;
        }

        setBusy(submitBtn, true, 'Signing in…');
        try {
            session = await nuvioLogin(email, password);
            // Session token in hand, so the password has no reason to stay in the DOM.
            modal.querySelector('#nuvioPassword').value = '';
            const profiles = await nuvioProfiles(session.token);

            if (profiles.length === 1) {
                await finishInstall(Number(profiles[0].profile_index) || 1, submitBtn);
            } else {
                const select = modal.querySelector('#nuvioProfileSelect');
                select.innerHTML = '';
                profiles.forEach(p => {
                    const id = Number(p.profile_index) || 1;
                    const option = document.createElement('option');
                    option.value = String(id);
                    option.textContent = p.name || `Profile ${id}`;
                    select.appendChild(option);
                });
                loginStep.classList.add('hidden');
                profileStep.classList.remove('hidden');
                status.classList.add('hidden');
            }
        } catch (err) {
            setStatus('error', `${err.message} ${FALLBACK_HINT}`);
        } finally {
            setBusy(submitBtn, false);
        }
    };

    const profileInstallBtn = modal.querySelector('#nuvioProfileInstallBtn');
    profileInstallBtn.onclick = () => {
        const profileId = Number(modal.querySelector('#nuvioProfileSelect').value) || 1;
        finishInstall(profileId, profileInstallBtn);
    };

    modal.classList.remove('hidden');
    modal.classList.add('flex');
}
