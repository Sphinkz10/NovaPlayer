package com.novacinema.connect

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.io.IOException
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Owned exclusively by :nova_overlay; every upstream preference is sealed, including identities. */
internal class TailscaleStateStore(context: Context) {
    private val prefs = context.getSharedPreferences("nova_tailscale_state", Context.MODE_PRIVATE)
    private val namespace = context.packageName + ":tailscale-state-v1:"
    private val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    private val alias = "nova-tailscale-state-v1"
    private fun key(create: Boolean): SecretKey {
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        if (!create || prefs.all.isNotEmpty()) throw IOException("Tailscale identity unavailable")
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    @Synchronized fun read(name: String): String {
        val raw = prefs.getString(name, null) ?: return ""
        require(raw.length <= 2_000_000)
        val sealed = Base64.decode(raw, Base64.NO_WRAP)
        require(sealed.size >= 28)
        return Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.DECRYPT_MODE, key(false), GCMParameterSpec(128, sealed.copyOfRange(0, 12)))
            updateAAD((namespace + name).toByteArray())
            String(doFinal(sealed.copyOfRange(12, sealed.size)), Charsets.UTF_8)
        }
    }
    @Synchronized fun write(name: String, value: String) {
        require(name.length in 1..512 && value.length <= 1_000_000)
        val sealed = Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.ENCRYPT_MODE, key(true)); updateAAD((namespace + name).toByteArray())
            iv + doFinal(value.toByteArray(Charsets.UTF_8))
        }
        check(prefs.edit().putString(name, Base64.encodeToString(sealed, Base64.NO_WRAP)).commit())
    }
    @Synchronized fun keys(): List<String> = prefs.all.keys.toList()
    // Upstream can recover from state-store errors by creating a new identity. Refuse to
    // initialize it at all when any previously stored entry cannot be authenticated.
    @Synchronized fun preflight() { keys().forEach { read(it) } }
}
