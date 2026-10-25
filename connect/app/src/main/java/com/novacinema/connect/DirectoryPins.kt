package com.novacinema.connect

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Public pins are authenticated/encrypted too: damaged state never becomes a fresh first lookup. */
class DirectoryPins(context:Context) {
    companion object { private val lock=Any() }
    private val prefs=context.getSharedPreferences("nova_directory_pins",Context.MODE_PRIVATE)
    private val alias="nova-directory-pins-v1"
    private val aad=(context.packageName+":directory-pins-v1").toByteArray(Charsets.UTF_8)
    private fun key(create:Boolean):SecretKey {
        val store=KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias,null) as? SecretKey)?.let { return it }
        check(create) { "Directory pin key missing" }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setRandomizedEncryptionRequired(true).build())
        }.generateKey()
    }
    fun accept(profile:DirectoryProfile,entry:DirectoryEntry):Unit = synchronized(lock) {
        val sealed=prefs.getString("sealed",null)
        val state=if(sealed==null)JSONObject().put("version",1).put("profile",profile.binding).put("entries",JSONObject()) else {
            require(sealed.length<=262144);val raw=Base64.decode(sealed,Base64.NO_WRAP);require(raw.size in 29..196608)
            val cipher=Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE,key(false),GCMParameterSpec(128,raw.copyOfRange(0,12)));cipher.updateAAD(aad)
            JSONObject(String(cipher.doFinal(raw.copyOfRange(12,raw.size)),Charsets.UTF_8))
        }
        require(state.integer("version")==1 && state.string("profile")==profile.binding)
        val entries=state.getJSONObject("entries");require(entries.length()<=100)
        if(entries.has(entry.id)) {
            val previous=entries.getJSONObject(entry.id)
            require(previous.string("key")==entry.publicKey && previous.string("server")==entry.trust.serverId &&
                previous.string("origin")==entry.trust.origin && previous.string("owner")==entry.owner && previous.whole("version")<=entry.version)
            if(previous.whole("version")==entry.version)require(previous.string("hash")==entry.payloadHash)
        } else require(entries.length()<100)
        entries.put(entry.id,JSONObject().put("key",entry.publicKey).put("server",entry.trust.serverId).put("origin",entry.trust.origin)
            .put("owner",entry.owner).put("version",entry.version).put("hash",entry.payloadHash))
        val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key(sealed==null));cipher.updateAAD(aad)
        val raw=cipher.iv+cipher.doFinal(state.toString().toByteArray(Charsets.UTF_8))
        check(prefs.edit().putString("sealed",Base64.encodeToString(raw,Base64.NO_WRAP)).commit())
    }
}

class DirectorySelection(val entry:DirectoryEntry,val account:String,val assertion:String)
object DirectorySelectionRuntime {
    private var selected:DirectorySelection?=null
    @Synchronized fun put(value:DirectorySelection) { selected=value }
    @Synchronized fun take():DirectorySelection = selected?.also { selected=null } ?: throw IllegalStateException("Selection expired")
}
