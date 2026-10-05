/**
 * Disasters & Hazards tab (Phase 1: GDACS + USGS) — presentation layer.
 *
 * Two sections — ACTIVE NOW and PREVIOUS — and only the selected one is
 * drawn on the globe. 'Active' comes from the backend (GDACS current
 * status + episode end date), never from "happened recently".
 *
 * Information hierarchy:
 *  - Default view = SIGNIFICANT events only (Red + Orange). Low-impact /
 *    unrated events are not plotted unless "Show low-impact events (N)"
 *    is enabled in Filters; then they are small and muted.
 *  - On the globe: ongoing significant events are full-strength; ended
 *    ones are quieter; approximate locations (GDACS area centres) get a
 *    dashed ring instead of a solid one. Colour encodes severity only.
 *  - Markers on the far side of the Earth are hidden (horizon occlusion)
 *    and dense areas cluster.
 *  - List rows show only hazard/location, date/status, severity.
 *    Provenance, uncertainty, impacts and geometry controls appear only
 *    in the opened event.
 * Data-honesty rules from Phase 1 are unchanged: one marker per linked
 * group, outline off by default with its caveat, figures with source and
 * as-of date side by side, per-source status (now in the footer details).
 */
class DisastersManager {
    static SEVERITY = {
        red:    { color: '#ef4444', label: 'Red', rank: 3 },
        orange: { color: '#f97316', label: 'Orange', rank: 2 },
        yellow: { color: '#eab308', label: 'Yellow', rank: 1.5 },
        green:  { color: '#5f8a6c', label: 'Green', rank: 1 },
        none:   { color: '#7c8796', label: 'Unrated', rank: 0 },
    };

    // 24×24 stroke glyphs (white on the severity disc). Simple, legible at 16px.
    static GLYPHS = {
        flood: '<path d="M3 9.5c1.5-1.6 3-1.6 4.5 0s3 1.6 4.5 0 3-1.6 4.5 0 3 1.6 4.5 0M3 14.5c1.5-1.6 3-1.6 4.5 0s3 1.6 4.5 0 3-1.6 4.5 0 3 1.6 4.5 0M3 19.5c1.5-1.6 3-1.6 4.5 0s3 1.6 4.5 0 3-1.6 4.5 0 3 1.6 4.5 0"/>',
        earthquake: '<path d="M2 12h4l2-5 3 11 3-14 2.5 11 1.5-3h4"/>',
        landslide: '<path d="M3 20h18M4 20 11 7l4 6"/><circle cx="16.5" cy="16" r="1.6"/><circle cx="19.5" cy="18.2" r="1.1"/><circle cx="13.6" cy="17.6" r="1"/>',
        tropical_cyclone: '<circle cx="12" cy="12" r="2.4"/><path d="M5.5 7.5A8 8 0 0 1 18.8 8M18.5 16.5A8 8 0 0 1 5.2 16"/>',
        volcano: '<path d="M3 20 9 11h6l6 9z"/><path d="M10 7.5c0-1.8 1.6-2.6 2.8-1.6.9-1.7 3.7-1.2 3.4.9"/>',
        drought: '<circle cx="12" cy="12" r="3.6"/><path d="M12 3v2.2M12 18.8V21M3 12h2.2M18.8 12H21M5.6 5.6l1.6 1.6M16.8 16.8l1.6 1.6M5.6 18.4l1.6-1.6M16.8 7.2l1.6-1.6"/>',
        wildfire: '<path d="M12 3c.8 3.6 5 5 5 10a5 5 0 0 1-10 0c0-2.6 1.6-3.8 1.9-5.6 1 .9 1.4 2 1.5 3.1C12 9 12.3 6.2 12 3z"/>',
        tornado: '<path d="M4 5h16M6 9h12M8 13h8M10 17h4M11 20.5h2"/>',
        heatwave: '<path d="M10 4.5a2 2 0 0 1 4 0v9.2a4 4 0 1 1-4 0z"/><path d="M12 9.5v6"/><path d="M17.5 5h2.5M17.5 8.5h2.5"/>',
        tsunami: '<path d="M3 17c2.5-5 6.5-10 11.5-10 2 0 3.3 1.1 3.3 3-1.8-.8-4 .2-4 2.2 0 2.8 3.6 3.7 6.2 2.8-1 2.4-4 4-8 4H3z"/>',
        earthquake_tsunami: '<path d="M2 9h3l1.5-3.5 2.5 7 2-4.5 1.5 2.5H15M3 19c2-1.6 4-1.6 6 0s4 1.6 6 0 4-1.6 6 0"/>',
        _default: '<path d="M12 4 21 20H3z"/><path d="M12 10v4M12 17v.5"/>',
    };

    constructor() {
        this.dataSource = null;
        this.section = 'active';           // 'active' | 'previous' — the ONLY layer on the globe
        this.range = '30';                 // Previous: '7' | '30' | 'custom'
        // Per section: significant response (GDACS Red/Orange) and the full
        // response (all alert levels, fetched for the low-impact count).
        this.data = { active: { sig: null, all: null }, previous: { sig: null, all: null } };
        this.keys = { active: null, previous: null };
        this.seq = { active: 0, previous: 0 };
        this.groups = [];
        this.selectedId = null;
        // Historical Extremes (third section): fetched on demand, cached per view/era.
        this.hist = { view: 'deadliest', era: 'since1900', data: {}, pending: {}, marker: null, selected: null };
        this.outlineEntity = null;
        this.uncertaintyEntity = null;
        this._iconCache = new Map();
        this._lastCamPos = null;
        this._bindControls();
    }

    // ---------------- lifecycle ----------------
    activate() {
        this._ensureDataSource();
        if (this.dataSource) this.dataSource.show = true;
        this._ensureLoaded('active');
        this._ensureLoaded('previous');
        if (this.section === 'historical') this._loadHistorical();
        this._render();
    }

    deactivate() {
        if (this.dataSource) this.dataSource.show = false;
    }

    _ensureDataSource() {
        const viewer = window.globeManager?.viewer;
        if (!viewer || this.dataSource) return;
        this.dataSource = new Cesium.CustomDataSource('disasters');
        this.dataSource.show = AppState.activeTab === 'disasters';
        this._setupClustering();
        viewer.dataSources.add(this.dataSource);
        // Horizon occlusion: markers use disableDepthTestDistance so terrain
        // never clips them; that would let far-side markers show THROUGH
        // the globe, so those are hidden explicitly.
        viewer.scene.preRender.addEventListener(() => this._updateOcclusion(viewer));
    }

    _updateOcclusion(viewer, force = false) {
        if (!this.dataSource || !this.dataSource.show) return;
        const cam = viewer.camera.positionWC;
        if (!force && this._lastCamPos && Cesium.Cartesian3.distance(cam, this._lastCamPos) < 2000) return;
        this._lastCamPos = Cesium.Cartesian3.clone(cam, this._lastCamPos);
        const occluder = new Cesium.EllipsoidalOccluder(Cesium.Ellipsoid.WGS84, cam);
        this.dataSource.entities.values.forEach(e => {
            if (!e._disCartesian) return;
            const visible = occluder.isPointVisible(e._disCartesian);
            if (e.show !== visible) e.show = visible;
        });
    }

    _setupClustering() {
        const c = this.dataSource.clustering;
        c.enabled = true;
        c.pixelRange = 34;
        c.minimumClusterSize = 3;
        c.clusterEvent.addEventListener((entities, cluster) => {
            const worst = entities.reduce((best, e) => {
                const r = DisastersManager.SEVERITY[e._disSeverity]?.rank ?? 0;
                return r > best.r ? { r, key: e._disSeverity } : best;
            }, { r: -1, key: 'none' });
            cluster.label.show = false;
            cluster.point.show = false;
            cluster.billboard.show = true;
            cluster.billboard.image = this._clusterIcon(entities.length, worst.key);
            cluster.billboard.width = 34;
            cluster.billboard.height = 34;
            cluster.billboard.disableDepthTestDistance = Number.POSITIVE_INFINITY;
        });
    }

    // ---------------- controls ----------------
    _bindControls() {
        const $ = (id) => document.getElementById(id);
        $('dis-sec-active')?.addEventListener('click', () => this.selectSection('active'));
        $('dis-sec-previous')?.addEventListener('click', () => this.selectSection('previous'));
        $('dis-sec-historical')?.addEventListener('click', () => this.selectSection('historical'));
        document.querySelectorAll('.dis-hist-view').forEach(btn => btn.addEventListener('click', () => {
            this.hist.view = btn.dataset.view;
            document.querySelectorAll('.dis-hist-view').forEach(b => b.classList.toggle('is-selected', b === btn));
            $('dis-era')?.classList.toggle('hidden', this.hist.view !== 'deadliest');
            this.showList();
            this._loadHistorical();
        }));
        document.querySelectorAll('.dis-era-btn').forEach(btn => btn.addEventListener('click', () => {
            this.hist.era = btn.dataset.era;
            document.querySelectorAll('.dis-era-btn').forEach(b => b.classList.toggle('is-selected', b === btn));
            this.showList();
            this._loadHistorical();
        }));
        document.querySelectorAll('.dis-range-btn').forEach(btn => btn.addEventListener('click', () => {
            this.range = btn.dataset.range;
            document.querySelectorAll('.dis-range-btn').forEach(b => b.classList.toggle('is-selected', b === btn));
            $('dis-custom-range')?.classList.toggle('hidden', this.range !== 'custom');
            if (this.range !== 'custom') this._reload('previous');
            else if ($('dis-start')?.value && $('dis-end')?.value) this._reload('previous');
        }));
        ['dis-start', 'dis-end'].forEach(id => $(id)?.addEventListener('change', () => {
            if ($('dis-start').value && $('dis-end').value) this._reload('previous');
        }));
        // Hazards / magnitude change what is fetched: reload both sections.
        const reloadBoth = () => { this._reload('active'); this._reload('previous'); };
        $('dis-eq-mag')?.addEventListener('change', reloadBoth);
        document.querySelectorAll('.dis-hazard-list input').forEach(cb => cb.addEventListener('change', reloadBoth));
        // Severity + low-impact are presentation filters (no refetch, except
        // fetching the full set the first time low-impact is enabled).
        $('dis-significance')?.addEventListener('change', () => this._render());
        $('dis-show-low')?.addEventListener('change', () => {
            if ($('dis-show-low').checked) this._ensureAll(this.section);
            this._render();
        });
        $('dis-back')?.addEventListener('click', () => this.showList());
    }

    selectSection(section) {
        if (section === this.section) return;
        this.section = section;
        const $ = (id) => document.getElementById(id);
        [['active', 'dis-sec-active'], ['previous', 'dis-sec-previous'], ['historical', 'dis-sec-historical']].forEach(([sec, id]) => {
            $(id)?.classList.toggle('is-selected', sec === section);
            $(id)?.setAttribute('aria-selected', String(sec === section));
        });
        $('dis-prev-controls')?.classList.toggle('hidden', section !== 'previous');
        $('dis-hist-controls')?.classList.toggle('hidden', section !== 'historical');
        // Hazard/severity filters belong to live events, not to history.
        $('dis-filters')?.classList.toggle('hidden', section === 'historical');
        this.showList();
        if (section === 'historical') { this._loadHistorical(); return; }
        this._ensureLoaded(section);
        if ($('dis-show-low')?.checked) this._ensureAll(section);
        this._render();
    }

    _hazards() {
        return [...document.querySelectorAll('.dis-hazard-list input:checked')].map(cb => cb.value).join(',');
    }

    _params(section) {
        const $ = (id) => document.getElementById(id);
        const p = { hazards: this._hazards(), eq_min_mag: $('dis-eq-mag')?.value || '5.0' };
        if (section === 'active') {
            // Wide enough to include long-running hazards (droughts) whose
            // current episode started weeks ago; the backend decides
            // 'active' from GDACS's own status + end date, not from this window.
            p.days = '60';
        } else if (this.range === 'custom') {
            p.start = $('dis-start')?.value || undefined;
            p.end = $('dis-end')?.value || undefined;
        } else {
            p.days = this.range;
        }
        return p;
    }

    // ---------------- data ----------------
    _ensureLoaded(section) {
        if (this.keys[section] !== JSON.stringify(this._params(section))) this._reload(section);
    }

    async _reload(section) {
        const seq = ++this.seq[section];
        const params = this._params(section);
        this.keys[section] = JSON.stringify(params);
        this.data[section] = { sig: null, all: null };
        if (section === this.section) this.showList();
        this._render();
        if (!params.hazards) return;
        const res = await api.get('/disasters', { ...params, min_alert: 'orange' });
        if (seq !== this.seq[section]) return;
        this.data[section].sig = res || { error: true };
        this._render();
        // The full set (for the low-impact count) loads in the background for
        // the section the user is looking at.
        if (section === this.section) this._ensureAll(section);
    }

    async _ensureAll(section) {
        const d = this.data[section];
        if (d.all || d.allPending || !d.sig || d.sig.error) return;
        d.allPending = true;
        const seq = this.seq[section];
        const res = await api.get('/disasters', { ...this._params(section), min_alert: 'all' });
        if (seq !== this.seq[section]) return;
        d.all = res || { error: true };
        d.allPending = false;
        this._render();
    }

    _sevKey(g) {
        // Group severity from the backend = highest of GDACS alert and the
        // same-event USGS PAGER level (audit fix C).
        const a = ((g.severity !== undefined ? g.severity : g.primary?.alert) || '').toLowerCase();
        return DisastersManager.SEVERITY[a] ? a : 'none';
    }

    _isSignificant(g) { return ['red', 'orange'].includes(this._sevKey(g)); }

    /** Groups of a response that belong to a section, split by significance. */
    _split(section, res) {
        const want = section === 'active' ? 'active' : 'ended';
        const inSection = (res?.groups || []).filter(g => g.status === want);
        return { sig: inSection.filter(g => this._isSignificant(g)), low: inSection.filter(g => !this._isSignificant(g)) };
    }

    // ---------------- render ----------------
    _render() {
        const $ = (id) => document.getElementById(id);
        const redOnly = $('dis-significance')?.value === 'red';
        const sevFilter = (gs) => redOnly ? gs.filter(g => this._sevKey(g) === 'red') : gs;

        // Section tab counts (compact previews).
        ['active', 'previous'].forEach(sec => {
            const el = $(sec === 'active' ? 'dis-count-active' : 'dis-count-previous');
            const d = this.data[sec].sig;
            if (!el) return;
            if (!this._hazards()) el.textContent = '0';
            else if (!d) el.textContent = '…';
            else if (d.error) el.textContent = '!';
            else el.textContent = String(sevFilter(this._split(sec, d).sig).length);
        });

        const sec = this.section;
        if (sec === 'historical') return this._renderHistorical();
        const d = this.data[sec];
        if (!this._hazards()) {
            this.groups = [];
            this._setSummary('No hazard types selected — open Filters.');
            return this._finishRender([], []);
        }
        if (!d.sig) {
            this._setSummary('Loading…');
            return this._finishRender([], [], true);
        }
        if (d.sig.error) {
            this.groups = [];
            this._setSummary('Could not reach the GaiaNet backend.');
            return this._finishRender([], []);
        }

        const sig = sevFilter(this._split(sec, d.sig).sig);
        const allOk = d.all && !d.all.error;
        const low = allOk ? this._split(sec, d.all).low : [];
        const partial = allOk && d.all.sources?.GDACS?.status === 'partial';
        const showLow = $('dis-show-low')?.checked;
        const lowLabel = $('dis-show-low-label');
        if (lowLabel) lowLabel.textContent = allOk
            ? `Show low-impact events (${low.length}${partial ? '+' : ''})`
            : 'Show low-impact events (counting…)';

        const nRed = sig.filter(g => this._sevKey(g) === 'red').length;
        const nOrange = sig.length - nRed;
        const breakdown = redOnly ? `${nRed} Red` : `${nRed} Red · ${nOrange} Orange`;
        let summary;
        if (sec === 'active') {
            summary = `${sig.length} active significant event${sig.length === 1 ? '' : 's'}`;
            if (sig.length) summary += ` · ${breakdown}`;
        } else {
            summary = `${breakdown} — ${sig.length} significant event${sig.length === 1 ? '' : 's'} · ${this._rangeLabel(d.sig)}`;
        }
        if (showLow && allOk) summary += ` · +${low.length}${partial ? '+' : ''} low-impact`;
        this._setSummary(summary);

        this.groups = showLow && allOk ? [...sig, ...low] : sig;
        this._finishRender(sig, showLow && allOk ? low : []);
    }

    _finishRender(sig, low, loading = false) {
        this._renderList(sig, low, loading);
        this._renderMarkers();
        this._renderSources();
        this._updateFiltersHint();
    }

    _rangeLabel(res) {
        if (this.range === 'custom') return `${this._fmtDate(res.from)} – ${this._fmtDate(res.to)}`;
        return `last ${this.range} days`;
    }

    _setSummary(text) {
        const el = document.getElementById('dis-summary');
        if (el) el.textContent = text;
    }

    _updateFiltersHint() {
        const all = document.querySelectorAll('.dis-hazard-list input').length;
        const on = document.querySelectorAll('.dis-hazard-list input:checked').length;
        const hint = document.getElementById('dis-filters-hint');
        if (!hint) return;
        const bits = [];
        if (document.getElementById('dis-significance')?.value === 'red') bits.push('Red only');
        if (on < all) bits.push(`${on} of ${all} hazards`);
        if (document.getElementById('dis-show-low')?.checked) bits.push('incl. low-impact');
        hint.textContent = bits.join(' · ');
    }

    _renderSources() {
        const dot = document.getElementById('dis-sources-dot');
        const body = document.getElementById('dis-sources-body');
        if (!dot || !body) return;
        if (this.section === 'historical') return this._renderHistSources();
        const d = this.data[this.section];
        const res = d.all && !d.all.error && document.getElementById('dis-show-low')?.checked ? d.all : d.sig;
        if (!res) { dot.className = 'dis-dot'; body.innerHTML = '<p>Loading…</p>'; return; }
        if (res.error) { dot.className = 'dis-dot dis-dot-error'; body.innerHTML = '<p>Backend unreachable.</p>'; return; }
        const statuses = Object.values(res.sources || {}).map(s => s.status);
        dot.className = 'dis-dot ' + (statuses.includes('error') ? 'dis-dot-error'
            : statuses.includes('partial') ? 'dis-dot-warn' : 'dis-dot-ok');
        const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
        const rows = Object.entries(res.sources || {}).map(([name, s]) =>
            `<li><b>${esc(name)}</b>: ${esc(s.status === 'ok' ? 'OK' : s.status === 'partial' ? 'partial' : 'unavailable')}, ${s.count} records${s.message ? `<br><span class="dis-muted">${esc(s.message)}</span>` : ''}</li>`).join('');
        const basis = this.section === 'active'
            ? '<p class="dis-muted">Active now = GDACS lists the event as current and its latest episode is recent. Earthquakes and other instantaneous USGS events are never "active"; they appear under Previous.</p>'
            : '';
        body.innerHTML = `<ul>${rows}</ul>${basis}
            <p class="dis-muted">Query window ${esc(res.from)} → ${esc(res.to)}. Updated ${esc(new Date(res.generated_at).toLocaleTimeString())}.</p>
            ${(res.notes || []).map(n => `<p class="dis-muted">${esc(n)}</p>`).join('')}`;
    }

    // ---------------- symbols ----------------
    _glyph(hazard) {
        const alias = { volcano_tsunami: 'volcano', volcanic_event: 'volcano' }[hazard] || hazard;
        return DisastersManager.GLYPHS[alias] || DisastersManager.GLYPHS._default;
    }

    /** Inline SVG icon for list rows / detail header (severity-coloured disc). */
    _iconSvg(hazard, sevKey, size = 28) {
        const color = DisastersManager.SEVERITY[sevKey].color;
        return `<svg class="dis-icon" width="${size}" height="${size}" viewBox="0 0 32 32" aria-hidden="true">
            <circle cx="16" cy="16" r="15" fill="${color}" fill-opacity="0.18" stroke="${color}" stroke-width="1.5"/>
            <g transform="translate(4 4)" fill="none" stroke="${color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${this._glyph(hazard)}</g>
        </svg>`;
    }

    /** Globe marker image. Variants encode hierarchy, never decoration. */
    _markerImage(hazard, sevKey, { approx, active, low }) {
        const key = `${hazard}|${sevKey}|${approx}|${active}|${low}`;
        if (this._iconCache.has(key)) return this._iconCache.get(key);
        const color = DisastersManager.SEVERITY[sevKey].color;
        const fill = approx ? `fill="${color}" fill-opacity="0.35"` : `fill="${color}"`;
        const ring = approx
            ? `<circle cx="24" cy="24" r="21" fill="none" stroke="${color}" stroke-width="2.5" stroke-dasharray="5 4"/>`
            : `<circle cx="24" cy="24" r="21" fill="none" stroke="#ffffff" stroke-opacity="${active && !low ? 0.95 : 0.35}" stroke-width="${active && !low ? 2.5 : 1.5}"/>`;
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
            <circle cx="24" cy="24" r="18" ${fill}/>${ring}
            <g transform="translate(12 12)" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${this._glyph(hazard)}</g></svg>`;
        const uri = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
        this._iconCache.set(key, uri);
        return uri;
    }

    _clusterIcon(count, sevKey) {
        const key = `cluster|${count}|${sevKey}`;
        if (this._iconCache.has(key)) return this._iconCache.get(key);
        const color = DisastersManager.SEVERITY[sevKey]?.color || DisastersManager.SEVERITY.none.color;
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
            <circle cx="24" cy="24" r="20" fill="#0b0f16" fill-opacity="0.85" stroke="${color}" stroke-width="3"/>
            <text x="24" y="29" text-anchor="middle" font-family="Inter,Arial,sans-serif" font-size="15" font-weight="700" fill="#ffffff">${count}</text></svg>`;
        const uri = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
        this._iconCache.set(key, uri);
        return uri;
    }

    // ---------------- list ----------------
    _renderList(sig, low, loading = false) {
        const listEl = document.getElementById('dis-list');
        if (!listEl) return;
        listEl.innerHTML = '';
        if (loading) return;
        const d = this.data[this.section].sig;
        if (!sig.length && !low.length) {
            if (d && !d.error && this._hazards()) {
                listEl.innerHTML = this.section === 'active'
                    ? '<p class="dis-empty">No significant events are currently listed as active by GDACS. '
                      + 'Recent earthquakes appear under Previous.</p>'
                    : '<p class="dis-empty">No significant events reported by GDACS or USGS for this period. '
                      + 'That does not mean nothing happened — Filters can include low-impact events.</p>';
            }
            return;
        }
        sig.forEach(g => listEl.appendChild(this._row(g, false)));
        if (low.length) {
            const h = document.createElement('p');
            h.className = 'dis-list-heading';
            h.textContent = `Low-impact & unrated (${low.length})`;
            listEl.appendChild(h);
            low.forEach(g => listEl.appendChild(this._row(g, true)));
        }
    }

    _row(g, isLow) {
        const p = g.primary;
        const sev = this._sevKey(g);
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'dis-row' + (isLow ? ' dis-row-low' : '');
        row.dataset.id = p.id;
        const status = g.status === 'active' ? 'Active' : 'Ended';
        row.innerHTML = `${this._iconSvg(p.hazard, sev, 28)}
            <span class="dis-row-main"><span class="dis-row-title"></span><span class="dis-row-sub"></span></span>
            <span class="dis-sev dis-sev-${sev}">${DisastersManager.SEVERITY[sev].label}</span>`;
        row.querySelector('.dis-row-title').textContent = this._shortTitle(p);
        row.querySelector('.dis-row-sub').textContent = `${this._fmtRange(p)} · ${status}`;
        row.addEventListener('click', () => this.selectGroup(p.id));
        return row;
    }

    _shortTitle(p) {
        if (p.source === 'USGS') {
            const place = (p.title.split(' — ')[1] || '').replace(/^\d+\s*km\s+[NSEW]{1,3}\s+of\s+/i, '');
            return `${p.hazard_label.replace(' (seismic signal)', '')}${p.magnitude != null ? ' M' + p.magnitude : ''} — ${place}`;
        }
        return p.title;
    }

    // ---------------- globe ----------------
    _renderMarkers() {
        this._ensureDataSource();
        if (!this.dataSource) return;
        if (this.section === 'historical') {
            // Historical: nothing in bulk — only the selected event's marker,
            // which must survive re-renders triggered by background loads.
            const keep = this.histMarker;
            this.dataSource.entities.removeAll();
            this.outlineEntity = null;
            this.uncertaintyEntity = null;
            this.histMarker = keep ? this.dataSource.entities.add(keep) : null;
            this._lastCamPos = null;
            return;
        }
        this.dataSource.entities.removeAll();
        this.outlineEntity = null;
        this.uncertaintyEntity = null;
        this.histMarker = null;
        // Low-impact drawn first so significant markers sit on top.
        const ordered = [...this.groups].sort((a, b) =>
            DisastersManager.SEVERITY[this._sevKey(a)].rank - DisastersManager.SEVERITY[this._sevKey(b)].rank);
        ordered.forEach(g => {
            const p = g.primary;
            const sev = this._sevKey(g);
            const low = !this._isSignificant(g);
            const active = g.status === 'active';
            const approx = g.marker.kind === 'area_centre';
            const size = low ? 14 : active ? 34 : 26;
            const position = Cesium.Cartesian3.fromDegrees(g.marker.lon, g.marker.lat);
            const ent = this.dataSource.entities.add({
                position,
                billboard: {
                    image: this._markerImage(p.hazard, sev, { approx, active, low }),
                    width: size, height: size,
                    color: Cesium.Color.WHITE.withAlpha(low ? 0.45 : active ? 1.0 : 0.6),
                    disableDepthTestDistance: Number.POSITIVE_INFINITY,
                    scaleByDistance: new Cesium.NearFarScalar(1.5e6, 1.15, 2.0e7, 0.75),
                },
            });
            ent._disasterGroupId = p.id;
            ent._disSeverity = sev;
            ent._disCartesian = position;
        });
        this._lastCamPos = null;
        const viewer = window.globeManager?.viewer;
        if (viewer) this._updateOcclusion(viewer, true);
    }

    // ---------------- detail ----------------
    async selectGroup(id) {
        const g = this.groups.find(gr => gr.primary.id === id);
        if (!g) return;
        this.selectedId = id;
        document.getElementById('dis-list-view')?.classList.add('hidden');
        document.getElementById('dis-detail-view')?.classList.remove('hidden');
        const body = document.getElementById('dis-detail-body');
        if (body) body.innerHTML = '<p class="dis-empty">Loading event details…</p>';

        window.globeManager?.viewer?.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(g.marker.lon, g.marker.lat, 900000),
            duration: 1.5,
        });

        const p = g.primary;
        const usgsRel = g.related.find(r => r.event.source === 'USGS');
        const [primaryDetail, usgsDetail] = await Promise.all([
            p.source === 'GDACS' ? api.get(`/disasters/gdacs/${p.gdacs_type}/${p.source_id}`)
                                 : api.get(`/disasters/usgs/${p.source_id}`),
            usgsRel ? api.get(`/disasters/usgs/${usgsRel.event.source_id}`) : Promise.resolve(null),
        ]);
        if (this.selectedId !== id) return;
        this._renderDetail(g, primaryDetail, usgsRel, usgsDetail);
        this._drawUncertainty(g, p.source === 'USGS' ? primaryDetail : usgsDetail);
    }

    showList() {
        this.selectedId = null;
        document.getElementById('dis-detail-view')?.classList.add('hidden');
        document.getElementById('dis-list-view')?.classList.remove('hidden');
        this._removeOverlay('outlineEntity');
        this._removeOverlay('uncertaintyEntity');
        this._removeOverlay('histMarker');
        if (this.hist) this.hist.selected = null;
    }

    _removeOverlay(prop) {
        // Overlays may be one entity or a list (multi-part outlines). Cesium
        // does not remove children with a parent, so pieces are tracked.
        const items = Array.isArray(this[prop]) ? this[prop] : (this[prop] ? [this[prop]] : []);
        if (this.dataSource) items.forEach(e => this.dataSource.entities.remove(e));
        this[prop] = null;
    }

    _drawUncertainty(g, usgsDetail) {
        this._removeOverlay('uncertaintyEntity');
        const err = usgsDetail?.event?.horizontal_error_km;
        if (!err || g.marker.kind === 'area_centre' || !this.dataSource) return;
        this.uncertaintyEntity = this.dataSource.entities.add({
            position: Cesium.Cartesian3.fromDegrees(g.marker.lon, g.marker.lat),
            ellipse: {
                semiMajorAxis: err * 1000, semiMinorAxis: err * 1000,
                material: Cesium.Color.WHITE.withAlpha(0.06),
                outline: true, outlineColor: Cesium.Color.WHITE.withAlpha(0.5),
                height: 0,
            },
        });
    }

    async _toggleOutline(g, on, noteEl) {
        this._removeOverlay('outlineEntity');
        if (!on) return;
        const p = g.primary;
        if (noteEl) noteEl.textContent = 'Loading GDACS reported area…';
        const geo = await api.get(`/disasters/gdacs/${p.gdacs_type}/${p.source_id}/geometry`, { episodeid: p.episode_id });
        if (this.selectedId !== p.id) return;
        if (!geo || geo.status !== 'ok' || !geo.geometry) {
            if (noteEl) noteEl.textContent = 'GDACS reported area not available for this event.';
            return;
        }
        const polys = geo.geometry.type === 'Polygon' ? [geo.geometry.coordinates] : geo.geometry.coordinates;
        const pieces = [];
        polys.forEach((poly) => {
            const outer = poly[0].flatMap(([lon, lat]) => [lon, lat]);
            pieces.push(this.dataSource.entities.add({
                polygon: {
                    hierarchy: Cesium.Cartesian3.fromDegreesArray(outer),
                    material: Cesium.Color.fromCssColorString('#94a3b8').withAlpha(0.12),
                    outline: true, outlineColor: Cesium.Color.fromCssColorString('#cbd5e1'),
                    height: 0,
                },
            }));
        });
        this.outlineEntity = pieces;
        if (noteEl) noteEl.textContent = `${geo.caveat}${geo.polygon_date ? ' Drawn as of ' + this._fmtDate(geo.polygon_date) + '.' : ''}`;
    }

    _renderDetail(g, primaryDetail, usgsRel, usgsDetail) {
        const body = document.getElementById('dis-detail-body');
        if (!body) return;
        const p = g.primary;
        const sev = this._sevKey(g);
        const esc = (s) => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
        const ue = usgsRel?.event || (p.source === 'USGS' ? p : null);
        const uDet = p.source === 'USGS' ? primaryDetail : usgsDetail;
        const gd = p.source === 'GDACS' ? primaryDetail : null;
        const status = g.status === 'active' ? 'Active now' : 'Ended';

        // --- 1. Headline: hazard/location, date/status, severity ---
        const head = `
            <div class="dis-detail-head">${this._iconSvg(p.hazard, sev, 36)}
                <div><h3 class="dis-detail-title">${esc(this._shortTitle(p))}</h3>
                <p class="dis-detail-sub">${esc(this._fmtRange(p))} · ${esc(status)}</p></div>
                <span class="dis-sev dis-sev-${sev}">${DisastersManager.SEVERITY[sev].label}</span>
            </div>
            ${gd?.alert_explanation ? `<p class="dis-explain">${esc(gd.alert_explanation)}</p>` : ''}`;

        // --- 2. What happened (timeline) ---
        const tl = [];
        if (ue) tl.push(`<li><b>${esc(this._fmtDateTime(ue.start))} UTC</b> — ${esc(ue.hazard_label)}${ue.magnitude != null ? ' M' + esc(ue.magnitude) : ''} (USGS)</li>`);
        if (uDet?.reclassification) tl.push(`<li>${esc(uDet.reclassification)}</li>`);
        if (p.source === 'GDACS') tl.push(`<li><b>${esc(this._fmtDate(p.start))} → ${esc(this._fmtDate(p.end))}</b> — GDACS episode</li>`);
        const timeline = tl.length ? `<section><h4>Timeline</h4><ul class="dis-timeline">${tl.join('')}</ul></section>` : '';

        // --- 3. Impacts: each source separately, with as-of date ---
        let impacts = '';
        if (gd?.status === 'ok' && gd.impacts?.length) {
            impacts += `<p class="dis-src-label">GDACS${gd.impacts_as_of ? ', as of ' + esc(gd.impacts_as_of) : ''}</p>
                <table class="dis-impacts"><tbody>
                ${gd.impacts.map(r => `<tr><td>${esc(r.label)}${r.note ? ` <span class="dis-note" title="${esc(r.note)}">*</span>` : ''}</td><td>${esc(r.country)}</td><td>${Number(r.value).toLocaleString()}</td></tr>`).join('')}
                </tbody></table>`;
        } else if (gd && gd.status !== 'ok') {
            impacts += '<p class="dis-muted">GDACS impact figures unavailable right now.</p>';
        }
        if (uDet?.impact_text) {
            impacts += `<p class="dis-src-label">USGS${uDet.impact_as_of ? ', as of ' + esc(uDet.impact_as_of) : ''}</p>
                <p class="dis-usgs-impact">${esc(uDet.impact_text)}</p>`;
        }
        if (gd?.impacts?.length && uDet?.impact_text) {
            impacts += '<p class="dis-muted">Figures differ by source and date; both are shown as published.</p>';
        }
        const impactSec = impacts ? `<section><h4>Reported impacts</h4>${impacts}</section>` : '';

        // --- 4. Location & map overlays ---
        const outlineCtl = p.source === 'GDACS' && ['FL', 'DR'].includes(p.gdacs_type) ? `
            <label class="dis-toggle"><input type="checkbox" id="dis-outline-toggle"> Show GDACS reported area</label>
            <p class="dis-muted" id="dis-outline-note">Off by default: analyst-drawn from administrative units, not the flooded extent; may omit affected areas.</p>` : '';
        const locSec = `<section><h4>Location</h4>
            <p class="dis-muted">${esc(g.marker.note)} <span class="dis-coords">${g.marker.lat.toFixed(3)}°, ${g.marker.lon.toFixed(3)}°</span></p>
            ${uDet?.event?.horizontal_error_km ? `<p class="dis-muted">USGS location uncertainty ±${esc(uDet.event.horizontal_error_km)} km (circle on map).</p>` : ''}
            ${outlineCtl}</section>`;

        // --- 5. Sources & provenance (collapsed) ---
        const links = [];
        if (p.report_url) links.push(`<a href="${esc(p.report_url)}" target="_blank" rel="noopener">${esc(p.source)} report</a>`);
        if (ue && ue !== p && ue.report_url) links.push(`<a href="${esc(ue.report_url)}" target="_blank" rel="noopener">USGS event page</a>`);
        const rel = usgsRel ? `<p class="dis-muted">USGS ${esc(usgsRel.event.source_id)}: ${esc({ linked: 'linked', same_event: 'same event', possibly_related: 'possibly related' }[usgsRel.relation] || usgsRel.relation)}${usgsRel.distance_to_area_km != null ? ` — ${esc(usgsRel.distance_to_area_km)} km from GDACS reported area (buffer ${esc(usgsRel.buffer_km)} km)` : ` — ${esc(usgsRel.distance_km)} km from GDACS point`}.</p>` : '';
        const overview = gd?.maps?.overviewmap;
        const srcSec = `<details class="dis-provenance"><summary>Sources &amp; data notes</summary>
            ${g.status_basis ? `<p class="dis-muted"><b>Status:</b> ${esc(g.status_basis)}</p>` : ''}
            ${rel}
            ${(g.possible_links || []).length ? `<p class="dis-muted">Possibly related (not confirmed, shown separately): ${g.possible_links.map(l => esc(l.id) + ' (' + esc(l.distance_km) + ' km)').join(', ')}.</p>` : ''}
            ${p.glide ? `<p class="dis-muted">GLIDE ${esc(p.glide)}</p>` : ''}
            ${p.country_note ? `<p class="dis-muted">${esc(p.country_note)}</p>` : ''}
            ${overview ? `<a href="${esc(overview)}" target="_blank" rel="noopener"><img class="dis-map-thumb" src="${esc(overview)}" alt="GDACS overview map" loading="lazy"></a>` : ''}
            <p class="dis-links">${links.join(' · ')}</p></details>`;

        body.innerHTML = head + timeline + impactSec + locSec + srcSec;
        const toggle = document.getElementById('dis-outline-toggle');
        if (toggle) toggle.addEventListener('change', (e) => this._toggleOutline(g, e.target.checked, document.getElementById('dis-outline-note')));
    }

    // ---------------- historical extremes ----------------
    static esc(s) {
        return String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    }

    _histKey() { return this.hist.view === 'deadliest' ? `deadliest:${this.hist.era}` : this.hist.view; }

    async _loadHistorical() {
        const key = this._histKey();
        const cached = this.hist.data[key];
        if ((cached && !cached.error) || this.hist.pending[key]) { this._render(); return; }
        this.hist.pending[key] = true;
        this._render();
        const res = this.hist.view === 'deadliest'
            ? await api.get('/historical/deadliest', { era: this.hist.era })
            : this.hist.view === 'heatwaves'
                ? await api.get('/historical/heatwaves')
                : await api.get('/historical/records');
        this.hist.pending[key] = false;
        this.hist.data[key] = res || { error: true };
        this._render();
    }

    _renderHistorical() {
        this.groups = [];
        this._renderMarkers();
        this._updateFiltersHint();
        const listEl = document.getElementById('dis-list');
        const key = this._histKey();
        const res = this.hist.data[key];
        this._renderHistSources();
        if (!listEl) return;
        listEl.innerHTML = '';
        if (!res) { this._setSummary('Loading…'); return; }
        if (res.error) {
            // api.get() returns null for both network failures and server
            // errors, so don't claim the backend is unreachable.
            this._setSummary('This view could not be loaded right now. Try again shortly; if it persists, check the backend console.');
            return;                               // retried when the view is reopened

        }
        if (this.hist.view === 'deadliest') {
            const era = this.hist.era === 'since1900' ? 'since 1900' : 'in recorded history';
            this._setSummary(`Deadliest natural disasters ${era} · estimated deaths`);
            (res.items || []).forEach(item => listEl.appendChild(this._histRow(item)));
            if (!(res.items || []).length) listEl.innerHTML = '<p class="dis-empty">No data available from the sources right now.</p>';
            const short = [];
            if ((res.items || []).some(i => i.rank_overlaps)) short.push('≈ rank uncertain');
            const n = (res.pending_review || []).length;
            if (n) short.push(`${n} held for review`);
            short.push('floods & cyclones may be incomplete');
            this._histNotes(listEl, short.join(' · '), [res.method, res.coverage]);
        } else if (this.hist.view === 'heatwaves') {
            this._setSummary('Deadliest heatwaves · estimated deaths');
            (res.items || []).forEach(item => listEl.appendChild(this._histRow(item)));
            const short = ['Statistical estimates, not counts — methods differ'];
            if ((res.items || []).some(i => i.rank_overlaps)) short.push('≈ rank uncertain');
            this._histNotes(listEl, short.join(' · '), [res.method, res.coverage]);
        } else {
            this._setSummary('Record holders · strictly defined metrics');
            (res.records || []).forEach(rec => listEl.appendChild(this._recordRow(rec)));
            this._histNotes(listEl, 'Each record uses one strictly defined metric', [
                'Physical records (magnitude, eruption size, run-up) come from USGS, NOAA NCEI and the Smithsonian; mortality records from NCEI, WMO and peer-reviewed studies.',
                'Casualty records are never updated automatically from preliminary figures; a new magnitude record needs USGS review and 30 days.',
                'Costliest disaster is not shown: no open, authoritative global dataset exists.',
            ]);
        }
    }

    /** One short muted line + a collapsed "About these figures" with the detail. */
    _histNotes(listEl, shortLine, details) {
        const E = DisastersManager.esc;
        const wrap = document.createElement('div');
        wrap.className = 'dis-hist-note';
        const body = (details || []).filter(Boolean).map(t => `<p class="dis-muted">${E(t)}</p>`).join('');
        wrap.innerHTML = `<p class="dis-muted">${E(shortLine)}</p>${body ? `<details class="dis-about"><summary>About these figures</summary>${body}</details>` : ''}`;
        listEl.appendChild(wrap);
    }

    _histIcon(hazard, size = 28) {
        const color = '#cbd5e1';     // history is not severity-coded
        return `<svg class="dis-icon" width="${size}" height="${size}" viewBox="0 0 32 32" aria-hidden="true">
            <circle cx="16" cy="16" r="15" fill="${color}" fill-opacity="0.08" stroke="${color}" stroke-opacity="0.55" stroke-width="1.2"/>
            <g transform="translate(4 4)" fill="none" stroke="${color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${this._glyph(hazard)}</g>
        </svg>`;
    }

    /** Log-scale bar (1,000 … 5,000,000): range low→high with a tick at the ranked value. */
    _rangeBar(deaths) {
        const lo = deaths.low ?? deaths.rank_value, hi = deaths.high ?? deaths.rank_value, v = deaths.rank_value;
        if (v == null) return '';
        const pos = (x) => Math.max(0, Math.min(100, (Math.log10(Math.max(x, 1000)) - 3) / (Math.log10(5e6) - 3) * 100));
        const a = pos(lo), b = pos(hi);
        return `<span class="dis-range-bar" aria-hidden="true"><span class="dis-range-span" style="left:${a}%;width:${Math.max(b - a, 0.8)}%"></span><span class="dis-range-tick" style="left:${pos(v)}%"></span></span>`;
    }

    _histRow(item) {
        const E = DisastersManager.esc;
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'dis-row dis-hist-row';
        row.dataset.id = item.id;
        row.innerHTML = `<span class="dis-rank">${item.rank}${item.rank_overlaps ? '<span class="dis-approx" title="Range overlaps with other events — order not certain">≈</span>' : ''}</span>
            ${this._histIcon(item.hazard, 26)}
            <span class="dis-row-main"><span class="dis-row-title">${E(item.title)}</span>
            <span class="dis-row-sub">${E(item.date_label)} · ${E(item.deaths.display)}${item.metric_type ? ` · <span class="dis-tag" title="${E(item.metric_label || '')}">${item.metric_type === 'excess_deaths' ? 'excess deaths' : 'modelled heat deaths'}</span>` : ''}${item.deaths.confidence === 'chronicle' ? ' · <span class="dis-tag" title="Single figure from pre-1900 historical records; uncertainty not quantified">historical estimate</span>' : ''}${(item.possible_duplicate_of || []).length ? ` · <span class="dis-tag" title="NCEI lists this separately, but it may be the same disaster">possibly same as #${item.possible_duplicate_of.join(', #')}</span>` : ''}</span>
            ${this._rangeBar(item.deaths)}</span>`;
        row.addEventListener('click', () => this.selectHistorical(item));
        return row;
    }

    _recordRow(rec) {
        const E = DisastersManager.esc;
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'dis-row dis-hist-row';
        row.dataset.id = rec.category;
        const h = rec.holder;
        row.innerHTML = `${this._histIcon(h?.hazard || 'earthquake', 26)}
            <span class="dis-row-main"><span class="dis-row-label">${E(rec.title)}</span>
            <span class="dis-row-title">${h ? E(h.title) : 'Unavailable right now'}</span>
            <span class="dis-row-sub">${h ? E(h.date_label) + ' · ' : ''}${E(rec.value_display || '—')}${rec.status === 'contested' ? ' · contested' : rec.status === 'estimated' ? ' · estimate' : ''}</span></span>`;
        if (h) row.addEventListener('click', () => this.selectHistorical(h, rec));
        else row.disabled = true;
        return row;
    }

    selectHistorical(item, record = null) {
        this.hist.selected = item.id;
        document.getElementById('dis-list-view')?.classList.add('hidden');
        document.getElementById('dis-detail-view')?.classList.remove('hidden');
        this._renderHistDetail(item, record);
        if (item.lat == null || item.lon == null) return;
        // Exactly one marker on the globe: the selected event.
        this._ensureDataSource();
        this._removeOverlay('histMarker');
        if (this.dataSource) {
            const position = Cesium.Cartesian3.fromDegrees(item.lon, item.lat);
            this.histMarker = this.dataSource.entities.add({
                position,
                billboard: {
                    image: this._histMarkerImage(item.hazard, item.location_approximate),
                    width: 34, height: 34,
                    disableDepthTestDistance: Number.POSITIVE_INFINITY,
                },
            });
            this.histMarker._disCartesian = position;
            this._lastCamPos = null;
        }
        window.globeManager?.viewer?.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(item.lon, item.lat, item.location_approximate ? 1500000 : 900000),
            duration: 1.8,
        });
    }

    _histMarkerImage(hazard, approx) {
        const key = `hist|${hazard}|${approx}`;
        if (this._iconCache.has(key)) return this._iconCache.get(key);
        const ring = approx
            ? '<circle cx="24" cy="24" r="21" fill="none" stroke="#e2e8f0" stroke-width="2.5" stroke-dasharray="5 4"/>'
            : '<circle cx="24" cy="24" r="21" fill="none" stroke="#ffffff" stroke-width="2.5"/>';
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
            <circle cx="24" cy="24" r="18" fill="#334155"/>${ring}
            <g transform="translate(12 12)" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${this._glyph(hazard)}</g></svg>`;
        const uri = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
        this._iconCache.set(key, uri);
        return uri;
    }

    _renderHistDetail(item, record) {
        const E = DisastersManager.esc;
        const body = document.getElementById('dis-detail-body');
        if (!body) return;
        const d = item.deaths;
        const fmt = (n) => Number(n).toLocaleString();
        const figVal = (f) => f.value != null ? `${fmt(f.value)}${f.unit ? ' ' + E(f.unit) : ''}` : `${fmt(f.value_low)}–${fmt(f.value_high)}`;

        let main = '';
        if (record && record.category === 'strongest_earthquake') {
            main = `<p class="dis-hist-figure">${E(record.value_display)}</p><p class="dis-muted">${E(record.metric_label)} · USGS${item.usgs_status ? ' · ' + E(item.usgs_status) : ''}</p>`;
        } else if (record && record.category === 'highest_tsunami_runup') {
            main = `<p class="dis-hist-figure">${E(record.value_display)}</p><p class="dis-muted">${E(record.metric_label)}</p>`;
        } else if (record && record.category === 'deadliest_tsunami') {
            main = `<p class="dis-hist-label">Deaths caused by the tsunami</p><p class="dis-hist-figure">${E(record.value_display)}</p>
                <p class="dis-muted">${E(record.metric_label)} · ${E(record.authority)}</p>
                ${d ? `<p class="dis-muted">Whole disaster (incl. earthquake): ${E(d.display)}</p>` : ''}`;
        } else if (record && record.category === 'largest_eruption') {
            main = `<p class="dis-hist-figure">${E(record.value_display)}</p><p class="dis-muted">${E(record.metric_label)}</p>`;
        } else if (d) {
            main = `<p class="dis-hist-label">${E(item.metric_label || 'Estimated deaths')}</p>
                <p class="dis-hist-figure">${E(d.display)}</p>
                ${d.best_note ? `<p class="dis-muted">${E(d.best_note)}</p>` : ''}
                ${this._rangeBar(d)}
                <p class="dis-muted"><b>Confidence:</b> ${E(d.confidence_label)}</p>`;
        }

        const figures = (d?.figures || item.figures || []);
        const figSec = figures.length ? `<section><h4>Estimates &amp; sources</h4><ul class="dis-fig-list">
            ${figures.map(f => `<li><b>${figVal(f)}</b> — ${E(f.label)}<br><span class="dis-muted">${f.url ? `<a href="${E(f.url)}" target="_blank" rel="noopener">${E(f.source)}</a>` : E(f.source)}</span></li>`).join('')}
            </ul></section>` : '';

        let recSec = '';
        if (record) {
            const bits = [`<p class="dis-muted"><b>${E(record.title)}</b> — ${E(record.basis)}</p>`, `<p class="dis-muted">Authority: ${E(record.authority)}</p>`];
            if ((record.shared_with || []).length) bits.push(`<p class="dis-muted">Shares the top value with: ${record.shared_with.map(x => E(`${x.title} (${x.date_label})`)).join('; ')}.</p>`);
            if (record.since1900) bits.push(`<p class="dis-muted">Since 1900: ${E(record.since1900.title)} (${E(record.since1900.date_label)}) — ${E(record.since1900.deaths?.display || '')}.</p>`);
            if ((record.pending_candidates || []).length) bits.push(`<p class="dis-muted">${record.pending_candidates.length} recent event${record.pending_candidates.length === 1 ? '' : 's'} with preliminary figures would exceed this; held for review, not promoted.</p>`);
            recSec = `<section><h4>Record</h4>${bits.join('')}</section>`;
        }

        let notes = d?.notes ? `<p class="dis-muted">${E(d.notes)}</p>` : '';
        if (item.metric_type) {
            notes += `<p class="dis-muted">Heat deaths are not counted individually; this is a statistical estimate. ${item.metric_type === 'excess_deaths'
                ? 'Excess deaths compare deaths observed with those expected for the period.'
                : 'Heat-attributable deaths are estimated from epidemiological models of temperature and mortality.'} Different studies and methods give different figures.</p>`;
        }
        if ((item.possible_duplicate_of || []).length) {
            notes += `<p class="dis-muted">NCEI lists this as a separate record, but it may be the same disaster as rank #${item.possible_duplicate_of.join(', #')} (same area, within a week). Both are shown as published; counts may be duplicated.</p>`;
        }
        if (item.has_tsunami && item.hazard !== 'earthquake_tsunami' && !(record && record.category === 'deadliest_tsunami')) {
            notes += `<p class="dis-muted">NCEI links this event to a tsunami record${item.tsunami_deaths != null ? ` (${Number(item.tsunami_deaths).toLocaleString()} tsunami deaths recorded)` : ''}; most deaths were not caused by the tsunami.</p>`;
        }
        const loc = `<section><h4>Location</h4><p class="dis-muted">${E(item.location_label || '')}${item.location_approximate ? ' — approximate' : ''}
            ${item.lat != null ? `<span class="dis-coords">${Number(item.lat).toFixed(2)}°, ${Number(item.lon).toFixed(2)}°</span>` : ''}</p></section>`;
        const prov = `<details class="dis-provenance"><summary>Data notes</summary>
            ${(item.linked_records || []).length ? `<p class="dis-muted">NCEI linked records: ${item.linked_records.map(m => E(`${m.kind} #${m.ncei_id}`)).join(', ')} (counted once, not summed).</p>` : ''}
            ${item.verified_on ? `<p class="dis-muted">Baseline entry verified on ${E(item.verified_on)}.</p>` : ''}
            ${item.usgs_url ? `<p class="dis-links"><a href="${E(item.usgs_url)}" target="_blank" rel="noopener">USGS event page</a></p>` : ''}
            </details>`;

        body.innerHTML = `
            <div class="dis-detail-head">${this._histIcon(item.hazard, 36)}
                <div><h3 class="dis-detail-title">${E(item.title)}</h3>
                <p class="dis-detail-sub">${E(item.hazard_label || '')} · ${E(item.date_label || '')}${item.date_note ? ' · ' + E(item.date_note) : ''}</p></div>
            </div>
            <section>${main}${notes}</section>${recSec}${figSec}${loc}${prov}`;
    }

    _renderHistSources() {
        const dot = document.getElementById('dis-sources-dot');
        const body = document.getElementById('dis-sources-body');
        if (!dot || !body) return;
        const res = this.hist.data[this._histKey()];
        if (!res) { dot.className = 'dis-dot'; body.innerHTML = '<p>Loading…</p>'; return; }
        if (res.error) { dot.className = 'dis-dot dis-dot-error'; body.innerHTML = '<p>Backend unreachable.</p>'; return; }
        const E = DisastersManager.esc;
        const st = Object.values(res.sources || {}).map(s => s.status);
        dot.className = 'dis-dot ' + (st.includes('unavailable') ? 'dis-dot-error' : st.includes('cached') ? 'dis-dot-warn' : 'dis-dot-ok');
        body.innerHTML = `<ul>${Object.entries(res.sources || {}).map(([k, v]) =>
            `<li><b>${E(k)}</b>: ${E(v.status)}${v.retrieved_at ? ` · ${E(new Date(v.retrieved_at).toLocaleDateString())}` : ''}${v.message ? `<br><span class="dis-muted">${E(v.message)}</span>` : ''}</li>`).join('')}</ul>
            <p class="dis-muted">Plus a small verified baseline (WMO records, floods, cyclones, documented ranges).</p>
            ${res.method ? `<p class="dis-muted">${E(res.method)}</p>` : ''}
            <p class="dis-muted">Costliest disasters are not shown: no open, authoritative global dataset exists.</p>`;
    }

    // ---------------- formatting ----------------
    _fmtDate(iso) {
        if (!iso) return '—';
        return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
    }

    _fmtDateTime(iso) {
        if (!iso) return '—';
        return new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
    }

    _fmtRange(p) {
        if (!p.end || p.source === 'USGS') return this._fmtDate(p.start);
        const s = new Date(p.start), e = new Date(p.end);
        const sameYear = s.getUTCFullYear() === e.getUTCFullYear();
        const a = s.toLocaleDateString(undefined, { day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }), timeZone: 'UTC' });
        return `${a} – ${this._fmtDate(p.end)}`;
    }
}

window.disastersManager = new DisastersManager();
