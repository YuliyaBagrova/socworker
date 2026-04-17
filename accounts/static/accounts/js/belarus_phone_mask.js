/**
 * Маска ввода: +375 (XX) XXX-XX-XX. Поля с классом js-belarus-phone.
 */
(function () {
    function digitsOnly(s) {
        return (s || '').replace(/\D/g, '');
    }

    function formatDisplay(d) {
        if (!d) return '';
        if (!d.startsWith('375') && d.length <= 9) d = '375' + d;
        d = d.slice(0, 12);
        if (d.length <= 3) return d.length ? '+' + d : '';
        var s = '+375 (' + d.slice(3, 5);
        if (d.length <= 5) return s;
        s += ') ' + d.slice(5, 8);
        if (d.length <= 8) return s;
        s += '-' + d.slice(8, 10);
        if (d.length <= 10) return s;
        s += '-' + d.slice(10, 12);
        return s;
    }

    function attach(el) {
        if (!el || el.dataset.byPhoneBound) return;
        el.dataset.byPhoneBound = '1';
        el.setAttribute('inputmode', 'tel');
        el.setAttribute('autocomplete', 'tel');

        el.addEventListener('input', function () {
            var d = digitsOnly(el.value);
            if (!d.startsWith('375') && d.length > 0 && d.length <= 9) d = '375' + d;
            d = d.slice(0, 12);
            var next = formatDisplay(d);
            el.value = next;
            try {
                el.setSelectionRange(next.length, next.length);
            } catch (e) { /* ignore */ }
        });

        el.addEventListener('blur', function () {
            var d = digitsOnly(el.value);
            if (d.length === 0) {
                el.value = '';
                return;
            }
            if (d.length === 9) d = '375' + d;
            if (d.length === 12 && d.startsWith('375')) {
                el.value = formatDisplay(d);
            }
        });
    }

    function init() {
        document.querySelectorAll('input.js-belarus-phone').forEach(attach);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
