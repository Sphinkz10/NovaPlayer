package com.novacinema.connect

import android.content.Context
import android.net.Uri
import androidx.media3.common.C
import androidx.media3.datasource.BaseDataSource
import androidx.media3.datasource.DataSpec
import java.io.InputStream
import java.io.IOException
import javax.net.ssl.HttpsURLConnection

/** Each extractor request uses the current NOVA session, pinned TLS and a fixed media route. */
@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
internal class NovaMediaSource(context:Context):BaseDataSource(true) {
    private val client=MediaClient(context.applicationContext)
    private var connection:HttpsURLConnection?=null
    private var input:InputStream?=null
    private var uri:Uri?=null
    private var remaining=0L
    private var opened=false
    override fun getUri()=uri
    override fun open(spec:DataSpec):Long {
        transferInitializing(spec)
        val saved=client.session()
        val expected=Regex("/api/v1/media/libraries/[a-f0-9]{32}/items/[a-f0-9]{32}/stream")
        if(spec.uri.toString()!=saved.trust.origin+spec.uri.path || !expected.matches(spec.uri.path.orEmpty()) ||
            spec.httpMethod!=DataSpec.HTTP_METHOD_GET || spec.httpBody!=null)throw IOException("Media route refused")
        val c=client.connection(spec.uri.path!!,saved);connection=c;uri=spec.uri
        try {
            val end=if(spec.length==C.LENGTH_UNSET.toLong())"" else (spec.position+spec.length-1).toString()
            c.setRequestProperty("Range","bytes=${spec.position}-$end")
            if(c.responseCode!=206 || c.contentEncoding?.let { it!="identity" }==true)throw IOException("Media range refused")
            val range=Regex("bytes (\\d+)-(\\d+)/(\\d+)").matchEntire(c.getHeaderField("Content-Range").orEmpty())
                ?: throw IOException("Media range invalid")
            remaining=c.getHeaderFieldLong("Content-Length",-1)
            if(range.groupValues[1].toLong()!=spec.position || remaining<=0 ||
                range.groupValues[2].toLong()-spec.position+1!=remaining)throw IOException("Media range invalid")
            input=c.inputStream;opened=true;transferStarted(spec);return remaining
        } catch(error:Exception) {
            c.disconnect();connection=null;uri=null
            if(error is IOException)throw error
            throw IOException("Media unavailable")
        }
    }
    override fun read(buffer:ByteArray,offset:Int,length:Int):Int {
        if(length==0)return 0
        if(remaining==0L)return C.RESULT_END_OF_INPUT
        val count=input?.read(buffer,offset,minOf(remaining,length.toLong()).toInt()) ?: throw IOException("Media closed")
        if(count<0)throw IOException("Media interrupted")
        remaining-=count;bytesTransferred(count);return count
    }
    override fun close() {
        try { input?.close() } finally {
            input=null;connection?.disconnect();connection=null;uri=null;remaining=0
            if(opened) { opened=false;transferEnded() }
        }
    }
}
