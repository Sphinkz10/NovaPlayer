package com.novacinema.connect

import android.content.Context
import android.content.pm.ApplicationInfo
import android.util.Base64
import com.novacinema.connect.core.*
import org.bouncycastle.crypto.params.Ed25519PublicKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer
import org.conscrypt.Conscrypt
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.Proxy
import java.net.URL
import java.security.cert.CertificateFactory
import javax.net.ssl.HttpsURLConnection

internal fun canonical(value:Any?):String = when(value) {
    null,JSONObject.NULL -> "null"
    is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(",","{","}") { canonical(it)+":"+canonical(value.get(it)) }
    is JSONArray -> (0 until value.length()).joinToString(",","[","]") { canonical(value.get(it)) }
    is String -> buildString {
        append('"');value.forEach { c -> append(when(c) {
            '"' -> "\\\""; '\\' -> "\\\\"; '\b' -> "\\b"; '\u000c' -> "\\f"; '\n' -> "\\n"; '\r' -> "\\r"; '\t' -> "\\t"
            else -> if(c.code<32 || c.code>126)"\\u"+c.code.toString(16).padStart(4,'0') else c.toString()
        }) };append('"')
    }
    is Int,is Long,is Boolean -> value.toString()
    else -> throw DeviceProtocolFailure()
}
internal fun JSONObject.exact(vararg fields:String) { require(keys().asSequence().toSet()==fields.toSet()) }
internal fun JSONObject.whole(name:String):Long {
    val value=get(name);require(value is Int || value is Long);return (value as Number).toLong()
}
internal fun decoded(value:String,size:Int):ByteArray {
    require(value.matches(Regex("[A-Za-z0-9_-]+")))
    val raw=Base64.decode(value,Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
    require(raw.size==size && Base64.encodeToString(raw,Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)==value)
    return raw
}
internal fun signed(payload:JSONObject,signature:String,public:String,domain:String) {
    val verifier=Ed25519Signer();verifier.init(false,Ed25519PublicKeyParameters(decoded(public,32),0))
    val bytes=(domain+canonical(payload)).toByteArray(Charsets.US_ASCII)
    verifier.update(bytes,0,bytes.size);require(verifier.verifySignature(decoded(signature,64)))
}

class DirectoryProfile(val origin:String,val certificateDer:ByteArray,val publicKey:String) {
    val tls=ServerTrust(origin,"00000000-0000-4000-8000-000000000001",certificateDer)
    init { decoded(publicKey,32) }
    val binding get()=ServerTrust.fingerprint((origin+"|"+publicKey).toByteArray(Charsets.US_ASCII))
    companion object {
        fun parse(raw:ByteArray):DirectoryProfile {
            require(raw.size in 1..16384);val data=JSONObject(String(raw,Charsets.UTF_8))
            data.exact("version","purpose","origin","certificate_pem","public_key")
            require(data.integer("version")==1 && data.string("purpose")=="nova-directory-bootstrap")
            val pem=data.string("certificate_pem")
            require(pem.matches(Regex("-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\\r\\n]+-----END CERTIFICATE-----\\s*")))
            val cert=CertificateFactory.getInstance("X.509").generateCertificate(pem.byteInputStream())
            return DirectoryProfile(data.string("origin"),cert.encoded,data.string("public_key"))
        }
        fun load(context:Context):DirectoryProfile {
            // Release provisioning is public deployment configuration in the signed APK.
            // Only an ADB-authorized debug installation can use the private laboratory file.
            val debug=context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE!=0
            val fixture=File(context.filesDir,"nova-directory.json")
            val raw=if(debug && fixture.isFile)fixture.inputStream().use { it.bounded(16384) }
                    else context.assets.open("nova-directory.json").use { it.bounded(16384) }
            return parse(raw)
        }
    }
}

class DirectoryEntry(val id:String,val owner:String,val name:String,val publicKey:String,val version:Long,
                     val trust:ServerTrust,val payloadHash:String) {
    companion object {
        fun verify(record:JSONObject,profile:DirectoryProfile,now:Long=System.currentTimeMillis()/1000):DirectoryEntry {
            record.exact("payload","signature");val p=record.getJSONObject("payload")
            p.exact("purpose","audience","owner_id","entry_id","challenge_id","nonce","public_key","descriptor",
                    "version","issued_at","proof_expires_at","expires_at")
            require(p.string("purpose")=="register-v1" && p.string("audience")==profile.origin)
            for(field in listOf("owner_id","entry_id","challenge_id"))require(ServerTrust.validId(p.string(field)))
            decoded(p.string("nonce"),32);val key=p.string("public_key");decoded(key,32)
            val issued=p.whole("issued_at");require(issued<=now+5 && p.whole("expires_at")==issued+3600 &&
                p.whole("proof_expires_at")==issued+60 && now<p.whole("expires_at") && p.whole("version")>=1)
            signed(p,record.string("signature"),key,"NOVA-DIRECTORY-REGISTRATION-v1\n")
            val d=p.getJSONObject("descriptor");d.exact("schema_version","server_id","name","client_origin","certificate_pem")
            require(d.integer("schema_version")==1)
            val name=d.string("name");require(name.isNotBlank() && name.length<=64 && name.none { it.isISOControl() })
            val pem=d.string("certificate_pem");require(pem.length<=6000 &&
                pem.matches(Regex("-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\\r\\n]+-----END CERTIFICATE-----\\s*")))
            val certificate=CertificateFactory.getInstance("X.509").generateCertificate(pem.byteInputStream())
            val trust=ServerTrust(d.string("client_origin"),d.string("server_id"),certificate.encoded)
            require(trust.certificate().subjectAlternativeNames.orEmpty().any { it[0]==7 && it[1]==URL(trust.origin).host })
            return DirectoryEntry(p.string("entry_id"),p.string("owner_id"),name,key,p.whole("version"),trust,
                ServerTrust.fingerprint(canonical(p).toByteArray(Charsets.US_ASCII)))
        }
    }
}

class DirectoryFailure(val status:Int):Exception("Directory operation refused")
class DirectoryClient(private val profile:DirectoryProfile) {
    private var token:String?=null
    var account:String?=null;private set
    private val sockets=PinnedServerTls.socketFactory(profile.tls,Conscrypt.newProvider(),tls13=true)
    private fun request(path:String,body:JSONObject?=null):JSONObject {
        val connection=URL(profile.origin+"/api/v1/directory/"+path).openConnection(Proxy.NO_PROXY) as HttpsURLConnection
        try {
            connection.sslSocketFactory=sockets;connection.instanceFollowRedirects=false
            connection.connectTimeout=5000;connection.readTimeout=5000;connection.useCaches=false
            connection.setRequestProperty("Accept","application/json");connection.setRequestProperty("Accept-Encoding","identity")
            connection.setRequestProperty("Cache-Control","no-store")
            token?.let { connection.setRequestProperty("Authorization","Bearer "+it) }
            if(body!=null) {
                val bytes=body.toString().toByteArray(Charsets.UTF_8);require(bytes.size<=8192)
                connection.requestMethod="POST";connection.doOutput=true
                connection.setRequestProperty("Content-Type","application/json")
                connection.setFixedLengthStreamingMode(bytes.size);connection.outputStream.use { it.write(bytes) }
            }
            val status=connection.responseCode;if(status !in setOf(200,201))throw DirectoryFailure(status)
            require(connection.contentType?.substringBefore(';')=="application/json")
            return JSONObject(connection.inputStream.use { String(it.bounded(2*1024*1024),Charsets.UTF_8) })
        } finally { connection.disconnect() }
    }
    fun login(username:String,password:String):String {
        require(username.matches(Regex("[a-z][a-z0-9_.-]{2,39}")) && password.length in 1..1024)
        val issuer=request("identity");issuer.exact("issuer","public_key","purpose")
        require(issuer.string("issuer")==profile.origin && issuer.string("public_key")==profile.publicKey &&
            issuer.string("purpose")=="associate-v1")
        val response=request("login",JSONObject().put("username",username).put("password",password))
        val access=response.string("access_token");val identity=response.string("account_id")
        require(validToken(access) && ServerTrust.validId(identity))
        token=access;account=identity;return identity
    }
    fun discover():List<DirectoryEntry> {
        require(account!=null);val response=request("servers");require(response.get("media_authorized")==false)
        val records=response.getJSONArray("servers");require(records.length()<=70)
        return (0 until records.length()).map { DirectoryEntry.verify(records.getJSONObject(it).getJSONObject("record"),profile) }
            .also { require(it.map { record -> record.id }.distinct().size==it.size) }
    }
    fun assertion(entry:DirectoryEntry):String {
        val response=request("assertions",JSONObject().put("entry_id",entry.id));response.exact("payload","signature")
        val p=response.getJSONObject("payload");p.exact("purpose","issuer","audience","entry_id","subject","username",
            "assertion_id","issued_at","expires_at")
        require(p.string("purpose")=="associate-v1" && p.string("issuer")==profile.origin && p.string("entry_id")==entry.id &&
            p.string("audience")==entry.trust.serverId && p.string("subject")==account && ServerTrust.validId(p.string("assertion_id")))
        require(p.string("username").matches(Regex("[a-z][a-z0-9_.-]{2,39}")))
        val now=System.currentTimeMillis()/1000;val issued=p.whole("issued_at")
        require(issued<=now+5 && p.whole("expires_at")==issued+90 && now<p.whole("expires_at"))
        signed(p,response.string("signature"),profile.publicKey,"NOVA-DIRECTORY-IDENTITY-v1\n")
        return response.toString()
    }
    fun close() {
        try { if(token!=null)request("logout",JSONObject()) } catch(_:Exception) { /* Bounded remote session expires. */ }
        finally { token=null;account=null }
    }
}
