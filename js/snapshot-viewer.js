class SnapshotViewer {
    constructor() {
        // Historical range: MODIS Terra true-color coverage begins Feb
        // 2000, so anything earlier would show today's imagery mislabeled
        // as history. Capped at the present year since there's no future
        // imagery to show either. This replaces the identical constants
        // that used to live on GlobeManager.
        this.TIMELINE_START_YEAR = 2000;
        this.TIMELINE_END_YEAR = new Date().getFullYear();

        this.panel = document.getElementById('snapshot-viewer');
        this.locationNameEl = document.getElementById('snapshot-location-name');
        this.yearBadgeEl = document.getElementById('snapshot-year-badge');
        this.primaryImg = document.getElementById('snapshot-primary');
        this.comparisonImg = document.getElementById('snapshot-comparison');
        this.splitClip = document.getElementById('snapshot-split-clip');
        this.splitHandle = document.getElementById('snapshot-split-handle');
        this.loadingEl = document.getElementById('snapshot-loading');
        this.frame = document.querySelector('.snapshot-viewer-frame');

        this.currentLat = null;
        this.currentLon = null;
        this.splitMode = false;

        this._primaryDate = null;   // "YYYY-MM-01"
        this._historicalDate = null;
        this._fetchDebounce = null;

        this._initSplitDrag();
    }

    // Builds a NASA GIBS/Worldview Snapshot API URL — a flat, already
    // rendered image for a bounding box + date, no WMTS tiling and no
    // Cesium imagery-layer management involved at all. See:
    // https://wvs.earthdata.nasa.gov/api/v1/snapshot
    // BBOX for CRS=EPSG:4326 is minLat,minLon,maxLat,maxLon (confirmed
    // against NASA Earthdata's own documented example request).
    buildSnapshotUrl(lat, lon, dateStr, spanDeg = 6) {
        const half = spanDeg / 2;
        const minLat = (lat - half).toFixed(4);
        const maxLat = (lat + half).toFixed(4);
        const minLon = (lon - half).toFixed(4);
        const maxLon = (lon + half).toFixed(4);
        const bbox = `${minLat},${minLon},${maxLat},${maxLon}`;

        const params = new URLSearchParams({
            REQUEST: 'GetSnapshot',
            TIME: dateStr,
            BBOX: bbox,
            CRS: 'EPSG:4326',
            LAYERS: 'MODIS_Terra_CorrectedReflectance_TrueColor',
            FORMAT: 'image/jpeg',
            WIDTH: '640',
            HEIGHT: '400'
        });

        return `https://wvs.earthdata.nasa.gov/api/v1/snapshot?${params.toString()}`;
    }

    // Opens the panel at a location and loads whatever date the primary
    // timeline slider is currently sitting at.
    show(lat, lon, name = null) {
        if (!this.panel) return;
        this.currentLat = lat;
        this.currentLon = lon;
        this.panel.classList.remove('hidden');

        if (this.locationNameEl) {
            this.locationNameEl.textContent = name || `${lat.toFixed(2)}, ${lon.toFixed(2)}`;
        }

        const primarySlider = document.getElementById('timeline-slider');
        const value = primarySlider ? primarySlider.value : 100;
        this.updateDate(value, 'primary');
    }

    hide() {
        if (!this.panel) return;
        this.panel.classList.add('hidden');
        clearTimeout(this._fetchDebounce);
    }

    // Public accessor for the date the primary timeline slider currently
    // represents (e.g. "2024-08-01") — used by ui.js's NDVI readout so it
    // tracks the same date the snapshot image is showing.
    get primaryDate() {
        return this._primaryDate;
    }

    _sliderValueToDate(value) {
        const startYear = this.TIMELINE_START_YEAR;
        const totalMonths = (this.TIMELINE_END_YEAR - startYear) * 12;
        const monthTotal = Math.floor((value / 100) * totalMonths);
        const year = startYear + Math.floor(monthTotal / 12);
        const month = (monthTotal % 12) + 1;
        return `${year}-${month.toString().padStart(2, '0')}-01`;
    }

    // Called on every slider 'input' event. Updates the year badge
    // immediately (cheap, instant) but debounces the actual image fetch —
    // a real NASA snapshot is a full image request, not a cheap tile, so
    // firing one per drag-tick would hammer the API and stack up
    // out-of-order loads exactly the way the old tile approach did.
    updateDate(value, type = 'primary') {
        if (this.currentLat === null || this.currentLon === null) return;
        const dateStr = this._sliderValueToDate(value);

        if (type === 'primary') {
            this._primaryDate = dateStr;
            if (this.yearBadgeEl) this.yearBadgeEl.textContent = dateStr.slice(0, 7);
        } else {
            this._historicalDate = dateStr;
        }

        clearTimeout(this._fetchDebounce);
        this._fetchDebounce = setTimeout(() => this._loadImages(), 250);
    }

    _loadImages() {
        if (this.currentLat === null || this.currentLon === null) return;
        if (this.loadingEl) this.loadingEl.classList.remove('hidden');

        const primaryDate = this._primaryDate || `${this.TIMELINE_END_YEAR}-01-01`;
        this._loadOne(this.primaryImg, this.buildSnapshotUrl(this.currentLat, this.currentLon, primaryDate));

        if (this.splitMode) {
            const historicalDate = this._historicalDate || `${this.TIMELINE_START_YEAR}-02-01`;
            this._loadOne(this.comparisonImg, this.buildSnapshotUrl(this.currentLat, this.currentLon, historicalDate));
        }
    }

    // Preloads into a detached Image() first, then swaps the visible
    // <img>'s src only once the new image has actually finished loading —
    // the old image stays on screen the whole time instead of flashing to
    // a broken/blank state mid-fetch.
    _loadOne(imgEl, url) {
        if (!imgEl) return;
        const probe = new Image();
        probe.onload = () => {
            imgEl.src = url;
            if (this.loadingEl) this.loadingEl.classList.add('hidden');
        };
        probe.onerror = () => {
            if (this.loadingEl) this.loadingEl.classList.add('hidden');
            console.error('GIBS snapshot failed to load:', url);
        };
        probe.src = url;
    }

    setSplitMode(enabled) {
        this.splitMode = enabled;
        if (!this.splitClip || !this.splitHandle) return;

        if (enabled) {
            this.splitClip.style.width = '50%';
            this.splitHandle.style.left = '50%';
            this.splitClip.classList.remove('hidden');
            this.splitHandle.classList.remove('hidden');
            this._syncSplitImageWidth();
            this._loadImages();
        } else {
            this.splitClip.classList.add('hidden');
            this.splitHandle.classList.add('hidden');
        }
    }

    // The comparison image inside the clip div needs to be the FULL
    // frame width (not 50%) so that as the clip div's own width changes
    // while dragging, the image just gets progressively revealed/hidden
    // by the overflow:hidden boundary rather than resized.
    _syncSplitImageWidth() {
        if (!this.frame || !this.comparisonImg) return;
        this.comparisonImg.style.width = `${this.frame.clientWidth}px`;
    }

    _initSplitDrag() {
        if (!this.splitHandle || !this.frame) return;
        let dragging = false;

        this.splitHandle.addEventListener('mousedown', () => { dragging = true; });
        document.addEventListener('mouseup', () => { dragging = false; });
        document.addEventListener('mousemove', (e) => {
            if (!dragging || !this.splitClip) return;
            const rect = this.frame.getBoundingClientRect();
            let pct = ((e.clientX - rect.left) / rect.width) * 100;
            pct = Math.max(0, Math.min(100, pct));
            this.splitHandle.style.left = `${pct}%`;
            this.splitClip.style.width = `${pct}%`;
        });

        window.addEventListener('resize', () => {
            if (this.splitMode) this._syncSplitImageWidth();
        });
    }
}
