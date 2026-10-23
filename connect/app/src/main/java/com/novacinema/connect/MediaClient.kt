package com.novacinema.connect

import android.content.Context
import com.novacinema.connect.core.*
import org.json.JSONObject
import java.io.IOException
import java.net.Proxy
import java.net.URL
import javax.net.ssl.HttpsURLConnection
import org.conscrypt.Conscrypt

internal val mediaId = Regex("[a-f0-9]{32}")
internal data class CinemaItem(val id:String,val name:String,val type:String,val series:String,
    val year:Int,val overview:String,val runtime:Long,val position:Long,val played:Boolean,
    val season:Int=0,val episode:Int=0)
internal data class CinemaPage(val items:List<CinemaItem>,val next:Int?)

internal class MediaClient(private val context:Context) {
    fun session():SavedDevice {
        if(DeviceAssociationRuntime.get(context).check().state!=PairingState.ASSOCIATED) throw IOException("Association unavailable")
        return DeviceSessionStore(context).load()?.takeIf { it.accountId!=null } ?: throw IOException("Account required")
    }
    fun connection(path:String,saved:SavedDevice):HttpsURLConnection {
        require(path.startsWith("/api/v1/media/libraries/") && !path.contains('#') && !path.contains(".."))
        return (URL(saved.trust.origin+path).openConnection(Proxy.NO_PROXY) as HttpsURLConnection).apply {
            sslSocketFactory=PinnedServerTls.socketFactory(saved.trust,Conscrypt.newProvider(),tls13=true)
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
            j.getLong("runtime_ticks").also { require(it in 0..10000000000000000L) },
            j.getLong("position_ticks").also { require(it in 0..10000000000000000L) },j.getBoolean("played"),
            j.optInt("season",0).also { require(it in 0..10000) }, j.optInt("episode",0).also { require(it in 0..100000) })
    }
    fun page(library:String,start:Int=0,search:String="",kind:String="all"):CinemaPage {
        require(start in 0..100000 && search.length<=100 && kind in setOf("all","movies","episodes","continue"))
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
        require(event in setOf("start","progress","stop") && position in 0..1000000000000L)
        request(path(library,id)+"/events",JSONObject().put("event",event).put("position_ticks",position*10000).put("paused",paused))
    }

    fun image(library:String,id:String,saved:SavedDevice):android.graphics.Bitmap? {
        // No disk cache: artwork is account-scoped and discarded on screen exit.
        val c=connection(path(library,id)+"/image",saved)
        try {
            c.setRequestProperty("Accept","image/jpeg,image/png,image/webp")
            if(c.responseCode in setOf(204,404))return null
            require(c.responseCode==200 && c.contentType?.substringBefore(';') in setOf("image/jpeg","image/png","image/webp") &&
                c.contentEncoding?.let { it!="identity" }!=true)
            val raw=c.inputStream.use { it.bounded(1048576) }
            val bounds=android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds=true }
            android.graphics.BitmapFactory.decodeByteArray(raw,0,raw.size,bounds)
            require(bounds.outWidth in 1..4096 && bounds.outHeight in 1..4096 && bounds.outWidth.toLong()*bounds.outHeight<=16777216)
            val options=android.graphics.BitmapFactory.Options().apply {
                inSampleSize=1
                while(bounds.outWidth/inSampleSize>320 || bounds.outHeight/inSampleSize>480)inSampleSize*=2
            }
            return android.graphics.BitmapFactory.decodeByteArray(raw,0,raw.size,options)
        } finally { c.disconnect() }
    }
}
