package com.novacinema.connect

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.conscrypt.Conscrypt
import org.json.JSONObject
import java.net.Proxy
import java.net.URL
import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.X509Certificate
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/** Owner-provided exact certificate fingerprint is the initial trust anchor. Never TOFU. */
internal object DirectoryBootstrap {
    fun fetch(origin:String,fingerprint:String):ByteArray {
        require(fingerprint.matches(Regex("[a-f0-9]{64}")))
        // Reuse the strict private origin grammar without accepting a DNS redirect/public endpoint.
        require(com.novacinema.connect.core.ServerTrust.validOrigin(origin))
        val expected=fingerprint.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
        var peer:ByteArray?=null
        val trust=object:X509TrustManager {
            override fun getAcceptedIssuers()=emptyArray<X509Certificate>()
            override fun checkClientTrusted(chain:Array<out X509Certificate>?,authType:String?) { throw java.security.cert.CertificateException("Client certificates refused") }
            override fun checkServerTrusted(chain:Array<out X509Certificate>?,authType:String?) {
                val leaf=chain?.firstOrNull() ?: throw java.security.cert.CertificateException("Certificate required")
                leaf.checkValidity()
                if(!MessageDigest.isEqual(MessageDigest.getInstance("SHA-256").digest(leaf.encoded),expected))
                    throw java.security.cert.CertificateException("Fingerprint mismatch")
                peer=leaf.encoded
            }
        }
        val tls=SSLContext.getInstance("TLSv1.3",Conscrypt.newProvider()).apply { init(null,arrayOf(trust),null) }
        val connection=URL(origin+"/api/v1/directory/bootstrap").openConnection(Proxy.NO_PROXY) as HttpsURLConnection
        try {
            connection.sslSocketFactory=tls.socketFactory // Keep platform hostname validation.
            connection.instanceFollowRedirects=false;connection.connectTimeout=5000;connection.readTimeout=5000;connection.useCaches=false
            connection.setRequestProperty("Accept","application/json");connection.setRequestProperty("Accept-Encoding","identity")
            if(connection.responseCode!=200 || connection.contentType?.substringBefore(';')!="application/json" ||
                connection.contentEncoding?.let { it!="identity" }==true)throw java.io.IOException("Bootstrap refused")
            val raw=connection.inputStream.use { it.bounded(16384) }
            val profile=DirectoryProfile.parse(raw)
            require(profile.origin==origin && peer?.let { MessageDigest.isEqual(it,profile.certificateDer) }==true)
            return raw
        } finally { connection.disconnect() }
    }
}

/** Persistent public configuration is authenticated so corruption cannot cause a new trust prompt. */
internal class DirectorySetupStore(context:Context) {
    companion object { private val lock=Any() }
    private val prefs=context.getSharedPreferences("nova_directory_setup",Context.MODE_PRIVATE)
    private val alias="nova-directory-setup-v1"
    private val aad=(context.packageName+":directory-setup-v1").toByteArray(Charsets.UTF_8)
    private fun key(create:Boolean):SecretKey {
        val store=KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias,null) as? SecretKey)?.let { return it }
        check(create) { "Setup key unavailable" }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    fun load():ByteArray?=synchronized(lock) {
        val encoded=prefs.getString("sealed",null) ?: return@synchronized null
        require(encoded.length<=24000);val raw=Base64.decode(encoded,Base64.NO_WRAP);require(raw.size in 29..16412)
        val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(false),GCMParameterSpec(128,raw.copyOfRange(0,12)))
        cipher.updateAAD(aad);cipher.doFinal(raw.copyOfRange(12,raw.size)).also { DirectoryProfile.parse(it) }
    }
    fun saveNew(raw:ByteArray):Unit=synchronized(lock) {
        val selected=DirectoryProfile.parse(raw)
        val existing=load()
        if(existing!=null) {
            val previous=DirectoryProfile.parse(existing)
            require(previous.binding==selected.binding && MessageDigest.isEqual(previous.certificateDer,selected.certificateDer))
            return@synchronized
        }
        val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key(true));cipher.updateAAD(aad)
        check(prefs.edit().putString("sealed",Base64.encodeToString(cipher.iv+cipher.doFinal(raw),Base64.NO_WRAP)).commit())
    }
}
