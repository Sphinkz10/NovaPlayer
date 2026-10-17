package com.novacinema.connect.core

/** No external test framework required; run with scripts/run_core_tests.sh. */
object POCTest {
    private var executed = 0
    private fun test(name: String, block: () -> Unit) {
        try { block(); executed++ }
        catch (e: Throwable) { throw AssertionError("FAILED $name", e) }
    }
    private fun eq(want: Any?, actual: Any?) { check(want == actual) { "Expected $want, obtained $actual" } }
    private val info = PublicServerInfo("server-123", "Jellyfin Server", true)
    private val lan = "https://192.168.50.10:8920"
    private val remote = "https://10.90.0.1:8920"
    private fun conn(lanOk:Boolean=false,hasProfile:Boolean=true,consent:Boolean=true,vpnUp:Boolean=true,lanUrl:String?=lan,remoteUrl:String?=remote)=
        ConnectionInputs(lanOk,hasProfile,consent,vpnUp,lanUrl,remoteUrl)
    private fun play(granted:Boolean=true,has:Boolean=true,vCodec:Boolean=true,aCodec:Boolean=true,remux:Boolean=true,bitrate:Double=15.0,capacity:Double=80.0,optin:Boolean=false,admin:Boolean=false)=
        PlaybackInputs(granted,has,vCodec,aCodec,remux,bitrate,capacity,optin,admin)

    @JvmStatic fun main(args: Array<String>) {
        test("LAN chosen if verified") { eq(LinkMode.LAN, ConnectionPolicy.decide(conn(lanOk=true)).mode) }
        test("LAN preferred over VPN") { eq(LinkReason.LAN_VERIFIED, ConnectionPolicy.decide(conn(lanOk=true, vpnUp=false)).reason) }
        test("unverified LAN ignored") { eq(LinkMode.PRIVATE_VPN, ConnectionPolicy.decide(conn()).mode) }
        test("no admin profile blocks") { eq(LinkReason.NEEDS_ADMIN_PROVISIONING, ConnectionPolicy.decide(conn(hasProfile=false)).reason) }
        test("missing remote config blocks") { eq(LinkReason.NEEDS_ADMIN_PROVISIONING, ConnectionPolicy.decide(conn(remoteUrl=null)).reason) }
        test("VPN system consent required") { eq(LinkReason.NEEDS_ANDROID_CONSENT, ConnectionPolicy.decide(conn(consent=false)).reason) }
        test("VPN tunnel must be up") { eq(LinkReason.NEEDS_VPN_CONNECTION, ConnectionPolicy.decide(conn(vpnUp=false)).reason) }
        test("verified private URL selected") { eq(remote, ConnectionPolicy.decide(conn()).baseUrl) }
        test("no URL on blocked state") { eq(null, ConnectionPolicy.decide(conn(consent=false)).baseUrl) }
        test("invalid remote URL never used") { eq(LinkMode.UNAVAILABLE, ConnectionPolicy.decide(conn(remoteUrl="http://outside.net")).mode) }
        test("bad LAN endpoint ignored") { eq(LinkMode.PRIVATE_VPN, ConnectionPolicy.decide(conn(lanOk=true,lanUrl="ftp://localhost")).mode) }
        test("public fallback never synthesized") { eq(null, ConnectionPolicy.decide(conn(hasProfile=false,lanUrl=null)).baseUrl) }
        test("verified public URL never used as LAN") { eq(LinkMode.PRIVATE_VPN, ConnectionPolicy.decide(conn(lanOk=true, lanUrl="https://8.8.8.8:443")).mode) }
        test("verified LAN public DNS fails closed without VPN") { eq(LinkMode.UNAVAILABLE, ConnectionPolicy.decide(conn(lanOk=true,lanUrl="https://public.example",hasProfile=false)).mode) }
        test("unresolved custom LAN name requires pinned resolution future work") { eq(LinkMode.PRIVATE_VPN, ConnectionPolicy.decide(conn(lanOk=true,lanUrl="https://lan.nova.internal:8920")).mode) }
        test("empty LAN address cannot bypass private validation") { eq(LinkMode.UNAVAILABLE, ConnectionPolicy.decide(conn(lanOk=true,lanUrl="",hasProfile=false)).mode) }
        test("numeric private LAN endpoint accepted") { check(EndpointValidator.isValidPrivateLan("https://192.168.50.10:8920")) }
        test("deny LAN public numeric endpoint") { check(!EndpointValidator.isValidPrivateLan("https://9.9.9.9:443")) }
        test("deny LAN DNS hostname in POC") { check(!EndpointValidator.isValidPrivateLan("https://example.local:8920")) }
        test("reject encoded path traversal") { check(!EndpointValidator.isValid("https://10.90.0.1/%2e%2e/admin",true)) }
        test("reject encoded backslash") { check(!EndpointValidator.isValid("https://10.90.0.1/%5cadmin",true)) }
        test("reject URL with unexpected surrounding whitespace") { check(!EndpointValidator.isValid(" https://10.90.0.1",true)) }
        test("reject URL with raw backslash") { check(!EndpointValidator.isValid("https://10.90.0.1/\\admin",true)) }


        listOf("ftp://host","http://outside.example","https://user:pass@server.net","https://host.net/?token=123",
            "https://host.net/#secret","https://host.net:0","https://host.net:99999","", "https://host.net/a/../b",
            "https://host.net/%2fetc","https://").forEachIndexed { index, url ->
            test("reject malformed/dangerous URL $index") { check(!EndpointValidator.isValid(url,true)) }
        }
        test("deny public remote https even if encrypted") { check(!EndpointValidator.isValid("https://1.1.1.1:8920", true)) }
        test("deny external DNS remote hostname") { check(!EndpointValidator.isValid("https://media.public.example", true)) }
        test("allow CGNAT private overlay") { check(EndpointValidator.isValid("https://100.100.100.100", true)) }
        test("deny loopback as VPN endpoint") { check(!EndpointValidator.isValid("https://127.0.0.1", true)) }
        test("deny link-local remote") { check(!EndpointValidator.isValid("https://169.254.10.1", true)) }
        test("allow HTTPS host") { check(EndpointValidator.isValid("https://10.90.0.1:8920",true)) }
        test("local HTTP disabled by default") { check(!EndpointValidator.isValid("http://127.0.0.1:9191",false)) }
        test("local loopback HTTP test allowance") { check(EndpointValidator.isValid("http://127.0.0.1:9191",false,true)) }
        test("no remote loopback HTTP") { check(!EndpointValidator.isValid("http://127.0.0.1:9191",true,true)) }
        test("public Jellyfin info path appended") { eq("/System/Info/Public", EndpointValidator.publicInfoUrl("https://jellyfin.lan").path) }
        test("proxy prefix retained") { eq("/jellyfin/System/Info/Public", EndpointValidator.publicInfoUrl("https://server.lan/jellyfin").path) }

        test("Jellyfin ready") { eq(JellyfinStatus.READY, JellyfinHealth.evaluate(200,info).status) }
        test("initial setup not playable") { eq(JellyfinStatus.SETUP_REQUIRED, JellyfinHealth.evaluate(200,info.copy(startupWizardCompleted=false)).status) }
        test("missing wizard flag fail closed") { eq(JellyfinStatus.UNEXPECTED_RESPONSE, JellyfinHealth.evaluate(200,info.copy(startupWizardCompleted=null)).status) }
        test("HTTP 200 without valid body fails") { eq(JellyfinStatus.UNEXPECTED_RESPONSE, JellyfinHealth.evaluate(200).status) }
        test("matching pinned server identity accepted") { eq(JellyfinStatus.READY, JellyfinHealth.evaluate(200,info,expectedServerId="server-123").status) }
        test("incorrect pinned server identity blocked") { eq(JellyfinStatus.SERVER_IDENTITY_MISMATCH, JellyfinHealth.evaluate(200,info,expectedServerId="other-server").status) }
        test("empty pinned identity blocked") { eq(JellyfinStatus.SERVER_IDENTITY_MISMATCH, JellyfinHealth.evaluate(200,info,expectedServerId="").status) }
        test("server mismatch not retryable") { check(!JellyfinHealth.evaluate(200,info,expectedServerId="untrusted").retryable) }
        test("server mismatch requires admin action") { eq(RetryAction.REQUIRE_USER_ACTION,RecoveryPolicy.action(JellyfinHealth.evaluate(200,info,expectedServerId="untrusted"))) }
        test("noncanonical Jellyfin product rejected") { eq(JellyfinStatus.UNEXPECTED_RESPONSE, JellyfinHealth.evaluate(200,info.copy(productName="Jellyfin")).status) }
        test("fake Jellyfin server rejected") { eq(JellyfinStatus.UNEXPECTED_RESPONSE, JellyfinHealth.evaluate(200,info.copy(productName="Fake Gateway")).status) }
        test("empty server ID rejected") { eq(JellyfinStatus.UNEXPECTED_RESPONSE, JellyfinHealth.evaluate(200,info.copy(serverId="")).status) }
        listOf(500,502,503,504,408,425).forEach { n -> test("transient server $n") {
            val r=JellyfinHealth.evaluate(n);eq(JellyfinStatus.TEMPORARILY_UNAVAILABLE,r.status);check(r.retryable)
        } }
        test("network outage retryable") { eq(JellyfinStatus.OFFLINE, JellyfinHealth.evaluate(null).status) }
        test("certificate validation issue requires user action") { eq(RetryAction.REQUIRE_USER_ACTION, RecoveryPolicy.action(JellyfinProbeResult(JellyfinStatus.TLS_VALIDATION_FAILED,false))) }
        test("permission-based connection failure requires user action") { eq(RetryAction.REQUIRE_USER_ACTION, RecoveryPolicy.action(JellyfinProbeResult(JellyfinStatus.SECURITY_BLOCKED,false))) }

        test("401 no blind retry") { eq(JellyfinStatus.AUTH_REQUIRED, JellyfinHealth.evaluate(401).status) }
        test("403 no blind retry") { eq(JellyfinStatus.FORBIDDEN, JellyfinHealth.evaluate(403).status) }
        test("404 wrong path") { eq(JellyfinStatus.WRONG_ENDPOINT, JellyfinHealth.evaluate(404).status) }
        test("429 retry with header") { eq(37, JellyfinHealth.evaluate(429,retryAfterSeconds=37).retryAfterSeconds) }
        test("429 retry header cap") { eq(3600, JellyfinHealth.evaluate(429,retryAfterSeconds=999999).retryAfterSeconds) }
        test("301 refused") { eq(JellyfinStatus.REDIRECT_REJECTED, JellyfinHealth.evaluate(301).status) }
        test("302 refused") { eq(JellyfinStatus.REDIRECT_REJECTED, JellyfinHealth.evaluate(302).status) }
        test("invalid 204 rejected") { eq(JellyfinStatus.UNEXPECTED_RESPONSE, JellyfinHealth.evaluate(204).status) }
        test("setup incomplete requires admin") { eq(RetryAction.REQUIRE_USER_ACTION, RecoveryPolicy.action(JellyfinHealth.evaluate(200, info.copy(startupWizardCompleted=false)))) }
        test("do not retry unauthorized") { eq(RetryAction.REQUIRE_USER_ACTION, RecoveryPolicy.action(JellyfinHealth.evaluate(401))) }
        test("no retry on success") { eq(RetryAction.NONE, RecoveryPolicy.action(JellyfinHealth.evaluate(200,info))) }
        test("first retry 1 second") { eq(1,RecoveryPolicy.retryDelaySeconds(0)) }
        test("retry backoff") { eq(16,RecoveryPolicy.retryDelaySeconds(4)) }
        test("retry capped") { eq(60,RecoveryPolicy.retryDelaySeconds(999)) }
        test("retry-after honored") { eq(29,RecoveryPolicy.retryDelaySeconds(2,29)) }

        test("direct play allowed") { eq(PlaybackOutcome.DIRECT_PLAY, PlaybackPolicy.decide(play())) }
        test("never play unauthorized") { eq(PlaybackOutcome.BLOCK_NO_ACCESS, PlaybackPolicy.decide(play(granted=false))) }
        test("never play missing media") { eq(PlaybackOutcome.BLOCK_NO_MEDIA, PlaybackPolicy.decide(play(has=false))) }
        test("unsupported audio requires conversion, not remux") { eq(PlaybackOutcome.AUDIO_TRANSCODE, PlaybackPolicy.decide(play(aCodec=false))) }
        test("audio codec mismatch blocked") { eq(PlaybackOutcome.BLOCK_UNSUPPORTED_AUDIO, PlaybackPolicy.decide(play(aCodec=false,remux=false))) }
        test("container mismatch can use remux without changing codecs") { eq(PlaybackOutcome.CONTAINER_REMUX, PlaybackPolicy.decide(play().copy(containerSupported=false, containerRemuxAllowed=true))) }
        test("unsupported container requires remux permission") { eq(PlaybackOutcome.BLOCK_UNSUPPORTED_CONTAINER, PlaybackPolicy.decide(play().copy(containerSupported=false))) }
        test("container remux cannot fix unsupported audio") { eq(PlaybackOutcome.BLOCK_UNSUPPORTED_AUDIO, PlaybackPolicy.decide(play(aCodec=false,remux=false).copy(containerSupported=false,containerRemuxAllowed=true))) }
        test("unsupported subtitle cannot silently burn into video") { eq(PlaybackOutcome.BLOCK_UNSUPPORTED_SUBTITLE, PlaybackPolicy.decide(play().copy(subtitleSupported=false))) }
        test("unsupported video blocked by default") { eq(PlaybackOutcome.BLOCK_UNSUPPORTED_VIDEO, PlaybackPolicy.decide(play(vCodec=false))) }
        test("admin alone insufficient for video transcode") { eq(PlaybackOutcome.BLOCK_UNSUPPORTED_VIDEO, PlaybackPolicy.decide(play(vCodec=false,admin=true))) }
        test("user alone insufficient for video transcode") { eq(PlaybackOutcome.BLOCK_UNSUPPORTED_VIDEO, PlaybackPolicy.decide(play(vCodec=false,optin=true))) }
        test("both approvals needed for video transcode") { eq(PlaybackOutcome.TRANSCODE_APPROVED, PlaybackPolicy.decide(play(vCodec=false,optin=true,admin=true))) }
        test("remote bandwidth limited") { eq(PlaybackOutcome.BLOCK_INSUFFICIENT_BANDWIDTH, PlaybackPolicy.decide(play(bitrate=35.0,capacity=30.0))) }
        test("bandwidth limit requires explicit dual approval") { eq(PlaybackOutcome.TRANSCODE_APPROVED, PlaybackPolicy.decide(play(bitrate=35.0,capacity=30.0,admin=true,optin=true))) }
        test("unmeasured bandwidth fails closed") { eq(PlaybackOutcome.BLOCK_INSUFFICIENT_BANDWIDTH,PlaybackPolicy.decide(play(capacity=0.0))) }
        test("NaN bandwidth fails closed") { eq(PlaybackOutcome.BLOCK_INSUFFICIENT_BANDWIDTH,PlaybackPolicy.decide(play(capacity=Double.NaN))) }
        test("no source even with transcode allowed") { eq(PlaybackOutcome.BLOCK_NO_MEDIA,PlaybackPolicy.decide(play(has=false,optin=true,admin=true))) }
        test("unauthorized even with transcode allowed") { eq(PlaybackOutcome.BLOCK_NO_ACCESS,PlaybackPolicy.decide(play(granted=false,optin=true,admin=true))) }

        test("host-only VPN route permitted") { check(RouteGuard.allowedHostRoutes("10.90.0.1/32",setOf("10.90.0.1"))) }
        test("two host-only VPN routes permitted") { check(RouteGuard.allowedHostRoutes("10.90.0.1/32,10.90.0.2/32",setOf("10.90.0.1","10.90.0.2"))) }
        for (bad in listOf("0.0.0.0/0","::/0","10.0.0.0/8","192.168.0.0/16","10.90.0.1/24","foo.example/32","","10.90.0.1/-1")) {
            test("reject broad/invalid VPN route $bad") { check(!RouteGuard.allowedHostRoutes(bad,setOf("10.90.0.1"))) }
        }
        test("reject unauthorised destination") { check(!RouteGuard.allowedHostRoutes("10.90.0.1/32",setOf("10.90.0.8"))) }
        test("deny duplicated private host route") { check(!RouteGuard.allowedHostRoutes("10.90.0.1/32,10.90.0.1/32",setOf("10.90.0.1"))) }
        test("deny empty route entry disguised in comma list") { check(!RouteGuard.allowedHostRoutes("10.90.0.1/32,",setOf("10.90.0.1"))) }
        test("deny empty gateway whitelist") { check(!RouteGuard.allowedHostRoutes("10.90.0.1/32", emptySet())) }
        test("deny unauthorized playback session") { check(!AuthorizationPolicy.mayIssuePlaybackSession(SessionAuthorization(true,false,true,true))) }
        test("deny missing playable path") { check(!AuthorizationPolicy.mayIssuePlaybackSession(SessionAuthorization(true,true,true,false))) }
        test("allow fully authorized session") { check(AuthorizationPolicy.mayIssuePlaybackSession(SessionAuthorization(true,true,true,true))) }
        val networkTests = JellyfinTransportTest.run()
        val providerTests = ProviderContractTest.run()
        println("NOVA Connect: $executed policy tests PASS; $networkTests HTTP transport tests PASS; $providerTests provider tests PASS; total ${executed + networkTests + providerTests}")
    }
}
