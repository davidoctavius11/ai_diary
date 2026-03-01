// frida_wechat_key.js — Frida 17 compatible

function hexOf(ptr, len) {
    var bytes = ptr.readByteArray(len);
    return Array.prototype.map.call(new Uint8Array(bytes), function(b) {
        return ('0' + b.toString(16)).slice(-2);
    }).join('');
}

function findExport(name) {
    var result = null;
    Process.enumerateModules().forEach(function(mod) {
        if (result) return;
        try {
            var exp = mod.findExportByName(name);
            if (exp) { result = exp; }
        } catch(e) {}
    });
    return result;
}

var pbkdf = findExport('CCKeyDerivationPBKDF');
if (pbkdf) {
    console.log('[+] Found CCKeyDerivationPBKDF at ' + pbkdf);
    Interceptor.attach(pbkdf, {
        onEnter: function(args) {
            var passLen = args[2].toInt32();
            if (passLen <= 0 || passLen > 256) return;
            var passHex = hexOf(args[1], passLen);
            console.log('');
            console.log('================================================================');
            console.log('WECHAT KEY (password fed to PBKDF2):');
            console.log(passHex);
            console.log('================================================================');
            console.log('Save it: echo "' + passHex + '" > /tmp/wechat_key.txt');
        }
    });
} else {
    console.log('[!] CCKeyDerivationPBKDF not found in any loaded module');
}

var hmac = findExport('CCHmac');
if (hmac) {
    console.log('[+] Found CCHmac at ' + hmac);
    Interceptor.attach(hmac, {
        onEnter: function(args) {
            var keyLen = args[2].toInt32();
            if (keyLen === 32 || keyLen === 64) {
                console.log('[CCHmac] key (' + keyLen + 'B): ' + hexOf(args[1], keyLen));
            }
        }
    });
} else {
    console.log('[!] CCHmac not found');
}

console.log('[*] Ready. Log out and back in to WeChat.');
