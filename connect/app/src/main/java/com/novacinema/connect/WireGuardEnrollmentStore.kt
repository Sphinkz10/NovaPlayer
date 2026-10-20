package com.novacinema.connect

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.novacinema.connect.core.SavedDevice
import com.novacinema.connect.core.ServerTrust
import com.wireguard.crypto.Key
import com.wireguard.crypto.KeyPair
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** The private WireGuard key is generated here and never sent to Core or Directory.
 * X25519 bytes are wrapped by an Android Keystore AES-GCM key, not hardware X25519.
 * Corruption/key loss must never silently rotate an already enrolled public key.
 */
class WireGuardEnrollmentStore(context: Context) {
    private val prefs = context.getSharedPreferences("nova_wireguard_enrollment", Context.MODE_PRIVATE)
    private val alias = "nova-wireguard-enrollment-v1"
    private val aad = (context.packageName + ":wireguard-enrollment-v1").toByteArray(Charsets.UTF_8)
    private fun wrappingKey(create: Boolean): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        check(create) { "WireGuard key unavailable" }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setRandomizedEncryptionRequired(true).build())
        }.generateKey()
    }
    private fun binding(saved: SavedDevice): String = ServerTrust.fingerprint(
        (saved.trust.serverId + "\n" + saved.trust.origin + "\n" + saved.tokens.deviceId + "\n" + saved.accountId.orEmpty())
            .toByteArray(Charsets.UTF_8))

    // App-wide lock also serializes independently constructed store instances.
    internal fun keys(saved: SavedDevice): KeyPair = synchronized(lock) {
        val bound = binding(saved)
        val encoded = prefs.getString("sealed", null)
        if (encoded != null) {
            try {
                require(encoded.length <= 4096)
                val bytes = Base64.decode(encoded, Base64.NO_WRAP)
                require(bytes.size in 29..2048)
                val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                cipher.init(Cipher.DECRYPT_MODE, wrappingKey(false), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
                cipher.updateAAD(aad)
                val json = JSONObject(String(cipher.doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8))
                require(json.integer("version") == 1 && json.string("binding") == bound)
                return@synchronized KeyPair(Key.fromBase64(json.string("private_key")))
            } catch (_: Exception) {
                throw IllegalStateException("WireGuard enrollment unavailable; reassociate the device")
            }
        }
        val pair = KeyPair()
        val raw = JSONObject().put("version", 1).put("binding", bound)
            .put("private_key", pair.privateKey.toBase64()).toString().toByteArray(Charsets.UTF_8)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, wrappingKey(true)); cipher.updateAAD(aad)
        val sealed = Base64.encodeToString(cipher.iv + cipher.doFinal(raw), Base64.NO_WRAP)
        check(prefs.edit().putString("sealed", sealed).commit())
        pair
    }
    fun publicKey(saved: SavedDevice): String = keys(saved).publicKey.toBase64()
    fun fingerprint(saved: SavedDevice): String = ServerTrust.fingerprint(keys(saved).publicKey.bytes)
    fun clear() = synchronized(lock) {
        check(prefs.edit().clear().commit())
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (store.containsAlias(alias)) store.deleteEntry(alias)
    }
    private companion object { val lock = Any() }
}
