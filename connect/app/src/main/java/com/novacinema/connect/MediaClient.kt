package com.novacinema.connect

import android.content.Context
import com.novacinema.connect.core.*
import org.json.JSONObject
import java.io.IOException
import java.net.Proxy
import java.net.URL
import javax.net.ssl.HttpsURLConnection

internal val mediaId = Regex("[a-f0-9]{32}")
internal data class CinemaItem(val id:String,val name:String,val type:String,val series:String,
    val year:Int,val overview:String,val runtime:Long,val position:Long,val played:Boolean)
internal data class CinemaPage(val items:List<CinemaItem>,val next:Int?)

internal class MediaClient(private val context:Context) {
    fun session():SavedDevice {
        if(DeviceAssociationRuntime.get(context).check().state!=PairingState.ASSOCIATED) throw IOException("Association unavailable")
        return DeviceSessionStore(context).load()?.takeIf { it.accountId!=null } ?: throw IOException("Account required")
    }
    fun connection(path:String,saved:SavedDevice):HttpsURLConnection {
        require(path.startsWith("/api/v1/media/libraries/") && !path.contains('#') && !path.contains(".."))
        return (URL(saved.trust.origin+path).openConnection(Proxy.NO_PROXY) as HttpsURLConnection).apply {
            sslSocketFactory=PinnedServerTls.socketFactory(saved.trust)
            instanceFollowRedirects=false;connectTimeout=5000;readTimeout=8000;useCaches=false
            setRequestProperty("Authorization","Bearer ${saved.tokens.access}")
            setRequestProperty("Accept-Encoding","identity");setRequestProperty("Cache-Control","no-store")
        }
    }
    private fun request(path:String,body:JSONObject?=null):JSONObject {
        val saved=session();val c=connection(path,saved)
        try {
            c.setRequestProperty("Accept","application/json")
            if(body!=null) {
                val bytes=body.toString().toByteArray(Charsets.UTF_8)
                c.requestMethod="POST";c.doOutput=true;c.setRequestProperty("Content-Type","application/json")
                c.setFixedLengthStreamingMode(bytes.size);c.outputStream.use { it.write(bytes) }
            }
            val code=c.responseCode
            if(code !in 200..299)throw IOException("Media request refused")
            if(c.contentType?.substringBefore(';')!="application/json" || c.contentEncoding?.let { it!="identity" }==true)
                throw DeviceProtocolFailure()
            return JSONObject(c.inputStream.use { it.bounded(262144) }.toString(Charsets.UTF_8))
        } finally { c.disconnect() }
    }
    private fun path(library:String,item:String?=null):String {
        require(mediaId.matches(library) && (item==null || mediaId.matches(item)))
        return "/api/v1/media/libraries/$library/items"+(item?.let { "/$it" } ?: "")
    }
    private fun item(j:JSONObject):CinemaItem {
        val id=j.string("id");val name=j.string("name");val type=j.string("type")
        require(mediaId.matches(id) && name.length<=200 && type in setOf("Movie","Episode"))
        return CinemaItem(id,name,type,j.string("series"),j.integer("year"),j.string("overview"),
            j.getLong("runtime_ticks").also { require(it>=0) },j.getLong("position_ticks").also { require(it>=0) },j.getBoolean("played"))
    }
    fun page(library:String,start:Int=0,search:String="",kind:String="all"):CinemaPage {
        require(start in 0..100000 && search.length<=100 && kind in setOf("all","movies","episodes"))
        val data=request(path(library)+"?start=$start&kind=$kind&search="+java.net.URLEncoder.encode(search,"UTF-8"))
        val saved=DeviceSessionStore(context).load() ?: throw DeviceProtocolFailure()
        require(data.string("server_id")==saved.trust.serverId && data.string("account_id")==saved.accountId && data.string("library_id")==library)
        val values=data.getJSONArray("items");require(values.length()<=24)
        val next=if(data.isNull("next"))null else data.integer("next").also { require(it==start+24) }
        return CinemaPage((0 until values.length()).map { item(values.getJSONObject(it)) },next)
    }
    fun detail(library:String,id:String):CinemaItem {
        val data=request(path(library,id));val saved=DeviceSessionStore(context).load() ?: throw DeviceProtocolFailure()
        require(data.string("server_id")==saved.trust.serverId && data.string("account_id")==saved.accountId &&
            data.string("library_id")==library && data.string("stream_path")==path(library,id)+"/stream" && data.string("method")=="DirectPlay")
        return item(data.getJSONObject("item")).also { require(it.id==id) }
    }
    fun event(library:String,id:String,event:String,position:Long,paused:Boolean) {
        require(event in setOf("start","progress","stop") && position>=0)
        request(path(library,id)+"/events",JSONObject().put("event",event).put("position_ticks",position*10000).put("paused",paused))
    }
}
