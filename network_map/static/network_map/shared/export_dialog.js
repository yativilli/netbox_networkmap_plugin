/*
 * Chrome shared by every picture export on a page: the dialog that asks for the
 * file format, and the two steps an exporter needs once an answer came back.
 */
(function () {
    // Rasterising multiplies the canvas, because a canton map printed at its natural size has labels too small to read; browsers cap canvas.
    const PNG_SCALE = 2;
    const PNG_MAX_EDGE = 2400;

    const LABELS_ID = 'network-map-export-dialog';
    const FALLBACK_LABELS = {
        title: 'Export as picture',
        choose: 'In which format should the picture be saved?',
        png: 'PNG',
        png_hint: 'Bitmap picture with a fixed number of pixels',
        svg: 'SVG',
        svg_hint: 'Vector drawing that stays sharp when it is printed large',
        cancel: 'Cancel',
    };

    function labels() {
        const merged = Object.assign({}, FALLBACK_LABELS);
        const node = document.getElementById(LABELS_ID);
        if (!node) return merged;
        try {
            return Object.assign(merged, JSON.parse(node.textContent));
        } catch (error) {
            return merged;
        }
    }

    const FORMATS = [
        { id: 'png', caption: 'png', hint: 'png_hint' },
        { id: 'svg', caption: 'svg', hint: 'svg_hint' },
    ];

    let panel = null;
    let lastFocused = null;
    let settle = null;

    function option(format, words, recommended) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'nm-export-format';
        button.dataset.format = format.id;
        if (recommended) button.classList.add('is-recommended');
        button.setAttribute('aria-describedby', `nm-export-${format.id}-hint`);

        const caption = document.createElement('span');
        caption.className = 'nm-export-format-name';
        caption.textContent = words[format.caption];

        const hint = document.createElement('span');
        hint.className = 'nm-export-format-hint';
        hint.id = `nm-export-${format.id}-hint`;
        hint.textContent = words[format.hint];

        button.append(caption, hint);
        return button;
    }

    function build(words, recommended) {
        const overlay = document.createElement('div');
        overlay.className = 'nm-export-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'nm-export-dialog';
        dialog.setAttribute('role', 'dialog');
        dialog.setAttribute('aria-modal', 'true');
        dialog.setAttribute('aria-labelledby', 'nm-export-title');

        const title = document.createElement('h3');
        title.className = 'nm-export-title';
        title.id = 'nm-export-title';
        title.textContent = words.title;

        const question = document.createElement('p');
        question.className = 'nm-export-question';
        question.textContent = words.choose;

        const formats = document.createElement('div');
        formats.className = 'nm-export-formats';
        FORMATS.forEach((format) => {
            formats.appendChild(option(format, words, format.id === recommended));
        });

        const cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.className = 'nm-export-cancel';
        cancel.textContent = words.cancel;

        dialog.append(title, question, formats, cancel);
        overlay.appendChild(dialog);
        return overlay;
    }

    function onKeydown(event) {
        if (event.key === 'Escape') {
            event.preventDefault();
            finish(null);
        }
    }

    function finish(answer) {
        const done = settle;
        settle = null;
        document.removeEventListener('keydown', onKeydown);
        if (panel) {
            panel.remove();
            panel = null;
        }
        if (lastFocused && lastFocused.isConnected) lastFocused.focus();
        lastFocused = null;
        if (done) done(answer);
    }

    // Resolves to 'png', 'svg', or null when the dialog was dismissed.
    function chooseFormat(options) {
        const requested = options && options.button ? options.button : null;
        const recommended = (options && options.recommended) === 'png' ? 'png' : 'svg';
        finish(null);
        const words = labels();
        panel = build(words, recommended);
        lastFocused = requested && requested.isConnected ? requested : null;

        panel.addEventListener('click', (event) => {
            const chosen = event.target.closest('.nm-export-format');
            if (chosen) {
                finish(chosen.dataset.format);
            } else if (event.target === panel || event.target.closest('.nm-export-cancel')) {
                finish(null);
            }
        });

        document.body.appendChild(panel);
        document.addEventListener('keydown', onKeydown);
        const focusTarget = panel.querySelector(
            '.nm-export-format.is-recommended'
        ) || panel.querySelector('.nm-export-cancel');
        if (focusTarget) focusTarget.focus();

        return new Promise((resolve) => { settle = resolve; });
    }

    function rasterize(source, width, height) {
        const scale = Math.min(PNG_SCALE, PNG_MAX_EDGE / Math.max(width, height, 1));
        return new Promise((resolve, reject) => {
            const image = new Image();
            const url = URL.createObjectURL(new Blob([source], { type: 'image/svg+xml;charset=utf-8' }));
            image.onload = () => {
                try {
                    const canvas = document.createElement('canvas');
                    canvas.width = Math.max(1, Math.round(width * scale));
                    canvas.height = Math.max(1, Math.round(height * scale));
                    const ctx = canvas.getContext('2d');
                    ctx.fillStyle = '#ffffff';
                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                    ctx.scale(scale, scale);
                    ctx.drawImage(image, 0, 0);
                    URL.revokeObjectURL(url);
                    canvas.toBlob(
                        (blob) => (blob ? resolve(blob) : reject(new Error('PNG encoding failed'))),
                        'image/png'
                    );
                } catch (error) {
                    URL.revokeObjectURL(url);
                    reject(error);
                }
            };
            image.onerror = () => {
                URL.revokeObjectURL(url);
                reject(new Error('SVG could not be rasterised'));
            };
            image.src = url;
        });
    }

    function download(blob, name) {
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = name;
        anchor.click();
        URL.revokeObjectURL(url);
    }

    function today() {
        return new Date().toISOString().slice(0, 10);
    }

    window.NetworkMapExport = { chooseFormat, rasterize, download, today };
})();
