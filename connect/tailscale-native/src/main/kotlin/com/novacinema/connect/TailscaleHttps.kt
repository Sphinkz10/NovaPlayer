package com.novacinema.connect

import org.conscrypt.Conscrypt
import org.json.JSONObject
import java.net.Proxy
import java.net.InetAddress
import java.net.Socket
import java.net.URL
import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.*

/** Exact approved CGNAT gateway, PKIX + leaf pin + platform hostname verification + TLS 1.3. */
internal object TailscaleHttps {
    fun identity(gateway: String, port: Int, certificate: ByteArray, token: String): JSONObject {
        require(TailscaleRoutePolicy.isOverlayV4(gateway) && port in 1..65535)
        require(token.matches(Regex("[A-Za-z0-9_-]{40,128}")) && certificate.size in 128..8192)
        val cert = (CertificateFactory.getInstance("X.509")
            .generateCertificate(certificate.inputStream()) as X509Certificate).apply { checkValidity() }
        val anchors = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
            load(null, null); setCertificateEntry("nova-approved-gateway", cert)
        }
        val delegate = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(anchors) }
            .trustManagers.filterIsInstance<X509TrustManager>().single()
        val pinned = object : X509TrustManager {
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                delegate.checkServerTrusted(chain, authType)
                check(chain.isNotEmpty() && MessageDigest.isEqual(chain[0].encoded, cert.encoded))
                chain[0].checkValidity()
            }
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) { error("Unsupported") }
            override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf(cert)
        }
        val tls = SSLContext.getInstance("TLSv1.3", Conscrypt.newProvider()).apply {
            init(null, arrayOf(pinned), null)
        }
        val connection = URL("https://$gateway:$port/api/v1/device/me").openConnection(Proxy.NO_PROXY) as HttpsURLConnection
        try {
            val sockets = tls.socketFactory
            connection.sslSocketFactory = object : SSLSocketFactory() {
                private fun strict(socket: Socket): Socket = (socket as SSLSocket).apply { enabledProtocols = arrayOf("TLSv1.3") }
                override fun getDefaultCipherSuites(): Array<String> = sockets.defaultCipherSuites
                override fun getSupportedCipherSuites(): Array<String> = sockets.supportedCipherSuites
                override fun createSocket(): Socket = strict(sockets.createSocket())
                override fun createSocket(s: Socket, h: String, p: Int, c: Boolean): Socket = strict(sockets.createSocket(s, h, p, c))
                override fun createSocket(h: String, p: Int): Socket = strict(sockets.createSocket(h, p))
                override fun createSocket(h: String, p: Int, a: InetAddress, l: Int): Socket = strict(sockets.createSocket(h, p, a, l))
                override fun createSocket(a: InetAddress, p: Int): Socket = strict(sockets.createSocket(a, p))
                override fun createSocket(a: InetAddress, p: Int, l: InetAddress, q: Int): Socket = strict(sockets.createSocket(a, p, l, q))
            }
            connection.instanceFollowRedirects = false; connection.useCaches = false
            connection.connectTimeout = 2500; connection.readTimeout = 2500
            connection.setRequestProperty("Authorization", "Bearer $token")
            connection.setRequestProperty("Accept-Encoding", "identity")
            check(connection.responseCode == 200)
            check(connection.contentType?.substringBefore(';') == "application/json")
            return JSONObject(connection.inputStream.use { String(it.bounded(16384), Charsets.UTF_8) })
        } finally { connection.disconnect() }
    }
}
