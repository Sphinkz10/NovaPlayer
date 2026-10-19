package com.novacinema.connect.core

import java.security.KeyStore
import java.security.MessageDigest
import java.security.Provider
import java.net.InetAddress
import java.net.Socket
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager
import javax.net.ssl.SSLSocket

/** Per-connection trust anchored in the explicitly imported certificate.
 * PKIX, dates, exact leaf pin and the platform HTTPS hostname verifier all apply.
 * No system-wide trust store or hostname verifier is modified.
 */
object PinnedServerTls {
    fun socketFactory(trust: ServerTrust,provider:Provider?=null,tls13:Boolean=false): SSLSocketFactory {
        val cert = trust.certificate().apply { checkValidity() }
        val anchors = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
            load(null, null); setCertificateEntry("nova-owner-confirmed", cert)
        }
        val factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(anchors) }
        val delegate = factory.trustManagers.filterIsInstance<X509TrustManager>().single()
        val pinned = object : X509TrustManager {
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                delegate.checkServerTrusted(chain, authType)
                if (chain.isEmpty()) throw CertificateException("Missing certificate")
                chain[0].checkValidity()
                if (!MessageDigest.isEqual(chain[0].encoded, cert.encoded)) throw CertificateException("Server identity changed")
            }
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {
                throw CertificateException("Client certificates not supported")
            }
            override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf(cert)
        }
        val context=if(provider==null)SSLContext.getInstance("TLS") else SSLContext.getInstance("TLS",provider)
        val sockets=context.apply { init(null,arrayOf(pinned),null) }.socketFactory
        return if(!tls13)sockets else object:SSLSocketFactory() {
            private fun strict(socket:Socket):Socket = (socket as SSLSocket).apply { enabledProtocols=arrayOf("TLSv1.3") }
            override fun getDefaultCipherSuites():Array<String> = sockets.defaultCipherSuites
            override fun getSupportedCipherSuites():Array<String> = sockets.supportedCipherSuites
            override fun createSocket():Socket = strict(sockets.createSocket())
            override fun createSocket(s:Socket,h:String,p:Int,c:Boolean):Socket = strict(sockets.createSocket(s,h,p,c))
            override fun createSocket(h:String,p:Int):Socket = strict(sockets.createSocket(h,p))
            override fun createSocket(h:String,p:Int,a:InetAddress,l:Int):Socket = strict(sockets.createSocket(h,p,a,l))
            override fun createSocket(a:InetAddress,p:Int):Socket = strict(sockets.createSocket(a,p))
            override fun createSocket(a:InetAddress,p:Int,l:InetAddress,q:Int):Socket = strict(sockets.createSocket(a,p,l,q))
        }
    }
}
