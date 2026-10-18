package com.novacinema.connect.core

import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/** Per-connection trust anchored in the explicitly imported certificate.
 * PKIX, dates, exact leaf pin and the platform HTTPS hostname verifier all apply.
 * No system-wide trust store or hostname verifier is modified.
 */
object PinnedServerTls {
    fun socketFactory(trust: ServerTrust): SSLSocketFactory {
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
        return SSLContext.getInstance("TLS").apply { init(null, arrayOf(pinned), null) }.socketFactory
    }
}
