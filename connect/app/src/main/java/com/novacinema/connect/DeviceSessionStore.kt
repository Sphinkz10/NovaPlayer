package com.novacinema.connect

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.novacinema.connect.core.*
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Separate from VPN provisioning. Backups/transfer are disabled in the application manifest. */
class DeviceSessionStore(private val context: Context) : DeviceVault {
    private val prefs = context.getSharedPreferences("nova_device_session", Context.MODE_PRIVATE)
    private val alias = "nova-device-session-v1"
    private val aad = (context.packageName + ":device-session-v1").toByteArray(Charsets.UTF_8)
    private fun key(create: Boolean): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val existing = store.getKey(alias, null) as? SecretKey
        if (existing != null) return existing
        check(create) { "Device key unavailable" }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setRandomizedEncryptionRequired(true).build())
        return generator.generateKey()
    }
    @Synchronized override fun save(value: SavedDevice) = persist(RemoteWireGuardRuntime.persistent(value))
    private fun persist(value: SavedDevice) {
        val json = JSONObject().put("version", 2).put("origin", value.trust.origin).put("server_id", value.trust.serverId)
            .put("account_id",value.accountId ?: JSONObject.NULL)
            .put("certificate", Base64.encodeToString(value.trust.certificateDer, Base64.NO_WRAP))
            .put("access", value.tokens.access).put("refresh", value.tokens.refresh).put("device_id", value.tokens.deviceId)
            .put("expires_in", value.tokens.expiresIn).put("refresh_expires_in", value.tokens.refreshExpiresIn)
            .put("refresh_deadline", value.refreshDeadline).put("refresh_pending", value.refreshPending)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key(create = true)); cipher.updateAAD(aad)
        val sealed = cipher.iv + cipher.doFinal(json.toString().toByteArray(Charsets.UTF_8))
        check(prefs.edit().putString("sealed", Base64.encodeToString(sealed, Base64.NO_WRAP)).commit())
    }
    override fun load(): SavedDevice? = loadBase()?.let { RemoteWireGuardRuntime.project(context,it) }
    @Synchronized internal fun loadBase(): SavedDevice? {
        val encoded = prefs.getString("sealed", null) ?: return null
        return try {
            require(encoded.length <= 32_768)
            val sealed = Base64.decode(encoded, Base64.NO_WRAP)
            require(sealed.size in 29..24_576)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(create = false), GCMParameterSpec(128, sealed.copyOfRange(0, 12)))
            cipher.updateAAD(aad)
            val json = JSONObject(String(cipher.doFinal(sealed.copyOfRange(12, sealed.size)), Charsets.UTF_8))
            require(json.integer("version") in 1..2)
            val account=if(json.isNull("account_id"))null else json.string("account_id").also { require(ServerTrust.validId(it)) }
            SavedDevice(ServerTrust.restore(json.string("origin"), json.string("server_id"), Base64.decode(json.string("certificate"), Base64.NO_WRAP)),
                DeviceTokens(json.string("access"), json.string("refresh"), json.string("device_id"), json.integer("expires_in"), json.integer("refresh_expires_in")),
                json.getLong("refresh_deadline"), json.getBoolean("refresh_pending"),account)
        } catch (_: Exception) {
            clear(); null // Never log decrypted state, JSON exceptions or credentials.
        }
    }
    @Synchronized override fun clear() {
        RemoteWireGuardRuntime.forget(context)
        WireGuardEnrollmentStore(context).clear()
        check(prefs.edit().remove("sealed").commit())
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (store.containsAlias(alias)) store.deleteEntry(alias)
    }
}

/** Activity recreation cannot create a second refresh worker for the same credentials. */
object DeviceAssociationRuntime {
    private var instance: DevicePairing? = null
    @Synchronized fun get(context: Context): DevicePairing = instance ?: DevicePairing(
        DeviceSessionStore(context.applicationContext), { DeviceClient(it) }).also { instance = it }
}
