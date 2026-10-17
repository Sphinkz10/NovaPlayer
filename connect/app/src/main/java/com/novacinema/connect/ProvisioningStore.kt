package com.novacinema.connect

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.nio.charset.StandardCharsets
import java.io.ByteArrayOutputStream
import java.io.ByteArrayInputStream
import java.io.DataOutputStream
import java.io.DataInputStream
import com.novacinema.connect.core.EndpointValidator
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Local POC encrypted storage; production must use authenticated admin provisioning. */
class ProvisioningStore(private val context: Context) {
    private val prefs = context.getSharedPreferences("nova_connect_secure", Context.MODE_PRIVATE)
    private val alias = "nova-connect-poc-profile-v3"
    private val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    private fun secretKey(): SecretKey {
        val current = store.getKey(alias, null) as? SecretKey
        if (current != null) return current
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setKeySize(256)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true)
            .build())
        return generator.generateKey()
    }

    /** Never call from guest UI. A signed short-lived invitation is a future requirement. */
    fun provisionAdminOnly(configText: String, jellyfinUrl: String, expectedServerId: String) {
        require(configText.length in 80..16_384)
        require(EndpointValidator.isValid(jellyfinUrl, vpn = true))
        require(expectedServerId.matches(Regex("[A-Za-z0-9-]{8,128}")))
        val payload = ByteArrayOutputStream().also { out ->
            DataOutputStream(out).use { data ->
                data.writeUTF("nova-profile-v3")
                data.writeUTF(jellyfinUrl)
                data.writeUTF(expectedServerId)
                data.writeUTF(configText)
            }
        }.toByteArray()
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        cipher.updateAAD((context.packageName + ":nova-profile-v3").toByteArray(StandardCharsets.UTF_8))
        val sealed = cipher.iv + cipher.doFinal(payload)
        require(prefs.edit().putString("sealed", Base64.encodeToString(sealed, Base64.NO_WRAP)).commit()) {
            "Could not persist secure profile"
        }
    }

    data class Provisioned(val jellyfinUrl: String, val config: String, val expectedServerId: String)

    fun load(): Provisioned? {
        val sealed = prefs.getString("sealed", null) ?: return null
        return try {
            val bytes = Base64.decode(sealed, Base64.NO_WRAP)
            if (bytes.size < 29 || bytes.size > 20_000) return null
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
            cipher.updateAAD((context.packageName + ":nova-profile-v3").toByteArray(StandardCharsets.UTF_8))
            val raw = cipher.doFinal(bytes.copyOfRange(12, bytes.size))
            DataInputStream(ByteArrayInputStream(raw)).use { input ->
                if (input.readUTF() != "nova-profile-v3") return null
                val url = input.readUTF()
                val server = input.readUTF()
                val config = input.readUTF()
                if (input.available() != 0 || !EndpointValidator.isValid(url, vpn = true) ||
                    !server.matches(Regex("[A-Za-z0-9-]{8,128}")) || config.length !in 80..16_384
                ) return null
                Provisioned(url, config, server)
            }
        } catch (_: Exception) {
            null // Never include config, URL or server ID in diagnostics.
        }
    }

    fun revokeLocal() {
        prefs.edit().remove("sealed").commit()
        if (store.containsAlias(alias)) store.deleteEntry(alias)
    }
}
