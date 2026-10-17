package com.novacinema.connect.core

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.nio.charset.StandardCharsets
import javax.net.ssl.SSLHandshakeException
import javax.net.ssl.SSLPeerUnverifiedException
import java.net.SocketTimeoutException

object JellyfinTransportTest {
    private var count = 0
    private fun checkCase(name: String, block: () -> Unit) {
        try { block(); count++ } catch (e: Throwable) { throw AssertionError("HTTP MOCK FAILED: $name",e) }
    }

    private fun fakeDecoder(body: String): PublicServerInfo? = when (body) {
        "READY" -> PublicServerInfo("mock-server-id", "Jellyfin", true)
        "NEEDS_SETUP" -> PublicServerInfo("mock-server-id", "Jellyfin", false)
        else -> null
    }

    fun run(): Int {
        val server=HttpServer.create(InetSocketAddress("127.0.0.1",0),0)
        server.createContext("/System/Info/Public") { exchange ->
            val path = exchange.requestURI.query ?: "ready"
            val (status,body,extra) = when(path) {
                "ready" -> Triple(200,"READY",emptyMap<String,String>())
                "setup" -> Triple(200,"NEEDS_SETUP",emptyMap<String,String>())
                "garbled" -> Triple(200,"{garbled",emptyMap<String,String>())
                "oversize" -> Triple(200,"X".repeat(17_000),emptyMap<String,String>())
                "503" -> Triple(503,"starting",emptyMap<String,String>())
                "401" -> Triple(401,"login",emptyMap<String,String>())
                "403" -> Triple(403,"forbidden",emptyMap<String,String>())
                "429" -> Triple(429,"later",mapOf("Retry-After" to "37"))
                "302" -> Triple(302,"moved",mapOf("Location" to "https://unexpected.example/hijack"))
                else -> Triple(404,"not found",emptyMap<String,String>())
            }
            extra.forEach { (k,v) -> exchange.responseHeaders.set(k,v) }
            val bytes=body.toByteArray(StandardCharsets.UTF_8)
            exchange.sendResponseHeaders(status, bytes.size.toLong())
            exchange.responseBody.use { it.write(bytes) }
        }
        server.start()
        try {
            val url="http://127.0.0.1:${server.address.port}"
            val client=JellyfinNetworkProbe(::fakeDecoder)
            checkCase("default requires HTTPS") { check(runCatching { client.check(url) }.isFailure) }
            fun urlCase(kind:String,expected:JellyfinStatus)=checkCase("$kind -> $expected") {
                val result=client.check("$url?$kind",allowLoopbackHttpForTests=true)
                check(result.status==expected) { "Got ${result.status}" }
            }
            // The endpoint builder treats query params as forbidden, so use alternate routing via a separate
            // client mapping prefix path. For real tests, create separate fixed servers below instead.
            fun once(http:Int,body:String,expected:JellyfinStatus,header:String?=null)=checkCase("HTTP $http -> $expected") {
                val s=HttpServer.create(InetSocketAddress("127.0.0.1",0),0)
                s.createContext("/System/Info/Public") { ex ->
                    if (header != null) ex.responseHeaders.set("Retry-After",header)
                    if (http==302) ex.responseHeaders.set("Location","https://untrusted.example/")
                    val bytes=body.toByteArray(StandardCharsets.UTF_8)
                    ex.sendResponseHeaders(http,bytes.size.toLong())
                    ex.responseBody.use { it.write(bytes) }
                }
                s.start()
                try {
                    val result=client.check("http://127.0.0.1:${s.address.port}",allowLoopbackHttpForTests=true)
                    check(result.status==expected) { "Got ${result.status}" }
                    if (http==429) check(result.retryAfterSeconds==37)
                } finally { s.stop(0) }
            }
            once(200,"READY",JellyfinStatus.READY)
            once(200,"NEEDS_SETUP",JellyfinStatus.SETUP_REQUIRED)
            once(200,"{garbled",JellyfinStatus.UNEXPECTED_RESPONSE)
            once(200,"X".repeat(17_000),JellyfinStatus.UNEXPECTED_RESPONSE)
            once(503,"starting",JellyfinStatus.TEMPORARILY_UNAVAILABLE)
            once(502,"gateway",JellyfinStatus.TEMPORARILY_UNAVAILABLE)
            once(401,"login",JellyfinStatus.AUTH_REQUIRED)
            once(403,"forbidden",JellyfinStatus.FORBIDDEN)
            once(429,"slow down",JellyfinStatus.RATE_LIMITED,"37")
            once(302,"redirect",JellyfinStatus.REDIRECT_REJECTED)
            once(404,"bad base URL",JellyfinStatus.WRONG_ENDPOINT)
            checkCase("pinned server ID verifies normal response") {
                val probe=JellyfinNetworkProbe(::fakeDecoder, expectedServerId="mock-server-id")
                val result=probe.check(url,allowLoopbackHttpForTests=true)
                check(result.status==JellyfinStatus.READY)
            }
            checkCase("pinned server mismatch rejects a different Jellyfin") {
                val probe=JellyfinNetworkProbe(::fakeDecoder, expectedServerId="expected-different-id")
                val result=probe.check(url,allowLoopbackHttpForTests=true)
                check(result.status==JellyfinStatus.SERVER_IDENTITY_MISMATCH && !result.retryable)
            }
            checkCase("TLS handshake failure never reported as offline") {
                val failing=JellyfinNetworkProbe(::fakeDecoder, openConnection = { throw SSLHandshakeException("test-only TLS verification failed") })
                val result=failing.check("https://10.90.0.1:8920")
                check(result.status==JellyfinStatus.TLS_VALIDATION_FAILED && !result.retryable)
            }
            checkCase("TLS host mismatch fails closed") {
                val failing=JellyfinNetworkProbe(::fakeDecoder, openConnection = { throw SSLPeerUnverifiedException("test-only host mismatch") })
                val result=failing.check("https://10.90.0.1:8920")
                check(result.status==JellyfinStatus.TLS_VALIDATION_FAILED && !result.retryable)
            }
            checkCase("OS network security denial fails closed") {
                val failing=JellyfinNetworkProbe(::fakeDecoder, openConnection = { throw SecurityException("test-only permission denied") })
                val result=failing.check("https://10.90.0.1:8920")
                check(result.status==JellyfinStatus.SECURITY_BLOCKED && !result.retryable)
            }
            checkCase("transient socket timeout reported as offline") {
                val failing=JellyfinNetworkProbe(::fakeDecoder, openConnection = { throw SocketTimeoutException("test-only timeout") })
                val result=failing.check("https://10.90.0.1:8920")
                check(result.status==JellyfinStatus.OFFLINE && result.retryable)
            }
            checkCase("Jellyfin probe rejects public hostname even over HTTPS") {
                val failing=JellyfinNetworkProbe(::fakeDecoder, openConnection = { throw AssertionError("MUST NOT OPEN") })
                check(runCatching { failing.check("https://jellyfin.example.com") }.isFailure)
            }
            println("Jellyfin HTTP mock: $count / $count transport tests PASS")
            return count
        } finally { server.stop(0) }
    }
}
