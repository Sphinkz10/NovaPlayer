package com.novacinema.connect.core

import java.nio.file.Files
import java.nio.file.Path
import java.io.IOException
import java.net.InetSocketAddress
import java.net.URL
import java.security.KeyStore
import javax.net.ssl.*
import com.sun.net.httpserver.HttpsServer
import com.sun.net.httpserver.HttpsConfigurator
import java.util.concurrent.Executors

object DevicePairingTest {
    private var count = 0
    private const val SERVER = "11111111-1111-4111-8111-111111111111"
    private const val DEVICE = "22222222-2222-4222-8222-222222222222"
    private const val ORIGIN = "https://127.0.0.1:8920"
    private fun test(name: String, action: () -> Unit) {
        try { action(); count++ } catch (error: Throwable) { throw AssertionError("PAIRING FAILED: $name", error) }
    }
    private fun rejects(action: () -> Unit) {
        try { action() } catch (_: Exception) { return }
        error("Expected rejection")
    }
    private fun rejectsTls(action: () -> Unit) {
        try { action() } catch (_: SSLException) { return }
        error("Expected TLS rejection")
    }
    private fun tokens(suffix: String = "a") = DeviceTokens("access-"+suffix.repeat(48), "refresh-"+suffix.repeat(48), DEVICE, 300, 3600)
    private class Vault : DeviceVault {
        var value: SavedDevice? = null
        var failWrite = false
        override fun load() = value
        override fun save(value: SavedDevice) { if (failWrite) throw IOException(); this.value = value }
        override fun clear() { value = null }
    }
    private class Api : DeviceTransport {
        var refreshes = 0
        var assertions = 0
        var polls = 0
        var expires = false
        var current = tokens()
        var descriptor = DeviceIdentity(SERVER, DEVICE, ORIGIN)
        var pollFailure: Exception? = null
        var identityFailure: Exception? = null
        var refreshAction: (() -> DeviceTokens)? = null
        override fun authorize(label: String) = DeviceGrant("secret-"+"s".repeat(48), "ABCD-EFGH", SERVER, 600, 5)
        override fun authorizeBound(label:String,assertion:String):DeviceGrant {
            check(assertion=="signed-fixture");assertions++;return authorize(label)
        }
        override fun poll(secret: String): DeviceTokens { polls++; pollFailure?.let { throw it }; return current }
        override fun identity(access: String): DeviceIdentity {
            identityFailure?.let { throw it }
            if (expires || access != current.access) throw DeviceApiFailure(401,"invalid_token")
            return descriptor
        }
        override fun refresh(secret: String): DeviceTokens {
            refreshes++
            refreshAction?.let { return it() }
            check(secret == current.refresh)
            current = tokens("b"); expires = false; return current
        }
        override fun logout(access: String) { expires = true }
    }

    fun run(): Int {
        val directory = Files.createTempDirectory("nova-pairing-tests-")
        val keystore = directory.resolve("fixture.p12")
        val certificate = directory.resolve("fixture.der")
        val keytool = Path.of(System.getProperty("java.home"), "bin", if (System.getProperty("os.name").startsWith("Windows")) "keytool.exe" else "keytool")
        fun command(vararg args: String) {
            val process = ProcessBuilder(keytool.toString(), *args).redirectErrorStream(true).start()
            process.inputStream.use { it.readBytes() }
            check(process.waitFor() == 0) { "Disposable keytool fixture failed" }
        }
        try {
            command("-genkeypair","-alias","test","-keyalg","RSA","-keysize","2048","-validity","2",
                "-dname","CN=NOVA test","-ext","SAN=ip:127.0.0.1","-storetype","PKCS12","-keystore",keystore.toString(),
                "-storepass","temporary-test-password","-noprompt")
            command("-exportcert","-alias","test","-keystore",keystore.toString(),"-storepass","temporary-test-password","-file",certificate.toString())
            val trust = ServerTrust(ORIGIN, SERVER, Files.readAllBytes(certificate))
            val base=SavedDevice(trust,tokens(),System.currentTimeMillis()+3600000)
            val now=System.currentTimeMillis()/1000
            fun overlay(server:String=SERVER,device:String=DEVICE,account:String?=null,origin:String=ORIGIN,
                control:String="https://controlplane.tailscale.com",gateway:String="https://100.64.0.1:9444",
                revision:Int=1,issued:Long=now,expires:Long=now+86400)=
                TailscaleProfile(base,server,device,account,origin,control,gateway,revision,issued,expires,now)
            test("Tailscale preserves existing certificate and server identity") {
                val p=overlay();check(p.trust.origin=="https://100.64.0.1:9444" && p.trust.serverId==SERVER &&
                    p.trust.certificateDer.contentEquals(trust.certificateDer) && p.gateway=="100.64.0.1")
            }
            test("Tailscale does not broaden existing private trust to public origins") {
                check(!ServerTrust.validOrigin("https://8.8.8.8:9444"))
                rejects { ServerTrust("https://8.8.8.8:9444",SERVER,trust.certificateDer) }
                rejects { ServerTrust.restore("https://8.8.8.8:9444",SERVER,trust.certificateDer) }
            }
            for(bad in listOf("https://10.0.0.1:9444","https://100.63.255.255:9444","https://100.128.0.1:9444",
                "https://100.064.0.1:9444","https://example.com:9444","https://100.64.0.1:9444/",
                "https://100.64.0.1:9444?x=1","https://100.64.0.1:9444#x","https://user@100.64.0.1:9444",
                "https://100.64.0.1:443","https://100.64.0.1:09444","http://100.64.0.1:9444")) {
                test("Tailscale rejects unapproved gateway form $bad") { rejects { overlay(gateway=bad) } }
            }
            test("Tailscale cross-server device account and LAN substitution refused") {
                rejects { overlay(server=DEVICE) };rejects { overlay(device=SERVER) }
                rejects { overlay(account=SERVER) };rejects { overlay(origin="https://10.0.0.2:9444") }
            }
            test("Tailscale expiry future skew and duration bounded") {
                rejects { overlay(expires=now) };rejects { overlay(issued=now+31) }
                rejects { overlay(expires=now+86401) };rejects { overlay(revision=0) }
            }
            for(bad in listOf("http://control.example","https://user@control.example","https://control.example/",
                "https://control.example?x=1","https://CONTROL.example","https://control.example:0443")) {
                test("Tailscale control origin rejects ambiguity $bad") { rejects { overlay(control=bad) } }
            }
            fun fixture(action: (DevicePairing,Vault,Api,LongArray) -> Unit) {
                val vault = Vault(); val api = Api(); val clock = longArrayOf(System.currentTimeMillis())
                val manager = DevicePairing(vault, { api }, { clock[0] })
                action(manager,vault,api,clock)
            }
            test("public bootstrap origin permits only explicit private HTTPS") {
                check(ServerTrust.validOrigin(ORIGIN)); check(ServerTrust.validOrigin("https://100.64.1.2:8920"))
            }
            for (url in listOf("http://127.0.0.1:8920","https://8.8.8.8:443","https://public.example:443",
                "https://10.1.1.1:443/path","https://user@10.1.1.1:443","https://10.1.1.1:443?token=x",
                "https://10.1.1.1:443#x","https://010.1.1.1:443","https://10.1.1.1","https://10.1.1.1:0"))
                test("reject bootstrap origin $url") { check(!ServerTrust.validOrigin(url)) }
            test("credentials never appear in model diagnostics") {
                val value = tokens(); check(!value.toString().contains(value.access)); check(!value.toString().contains(value.refresh))
            }
            test("server lifetime limits cannot be broadened") { rejects { DeviceTokens("a".repeat(48),"b".repeat(48),DEVICE,301,3600) } }
            test("pending polling obeys deadline and interval") { fixture { manager,vault,api,clock ->
                check(manager.begin(trust,"TV").state == PairingState.WAITING)
                check(manager.poll().state == PairingState.WAITING && api.polls == 0)
                clock[0] += 5000; api.pollFailure = DeviceApiFailure(400,"authorization_pending",5)
                check(manager.poll().state == PairingState.WAITING && api.polls == 1)
                clock[0] += 5000; api.pollFailure = DeviceApiFailure(429,"slow_down",20)
                val wait = manager.poll(); check(wait.nextPollMillis == clock[0]+20000)
                clock[0] += 601000; check(manager.poll().state == PairingState.EXPIRED && vault.value == null)
            } }
            test("approval persists then validates identity") { fixture { manager,vault,_,clock ->
                manager.begin(trust,"TV"); clock[0]+=5000
                check(manager.poll().state == PairingState.ASSOCIATED && vault.value != null)
                check(DevicePairing(vault,{Api()},{clock[0]}).check().state == PairingState.ASSOCIATED)
            } }
            test("denial does not create a local session") { fixture { manager,vault,api,clock ->
                manager.begin(trust,"TV"); clock[0]+=5000; api.pollFailure=DeviceApiFailure(400,"access_denied")
                check(manager.poll().state==PairingState.DENIED && vault.value==null)
            } }
            test("lost poll response requires a fresh association") { fixture { manager,vault,api,clock ->
                manager.begin(trust,"TV"); clock[0]+=5000; api.pollFailure=IOException()
                check(manager.poll().state==PairingState.REASSOCIATE && vault.value==null)
                manager.poll(); check(api.polls==1)
            } }
            test("identity change fails closed and erases authorization") { fixture { manager,vault,api,clock ->
                manager.begin(trust,"TV"); clock[0]+=5000; api.descriptor=api.descriptor.copy(serverId=DEVICE)
                check(manager.poll().state==PairingState.SECURITY_ERROR && vault.value==null)
            } }
            test("descriptor origin cannot redirect the client") { fixture { manager,vault,api,clock ->
                manager.begin(trust,"TV"); clock[0]+=5000; api.descriptor=api.descriptor.copy(origin="https://8.8.8.8:443")
                check(manager.poll().state==PairingState.SECURITY_ERROR && vault.value==null)
            } }
            test("temporary failure retains association but does not claim connected") { fixture { manager,vault,api,clock ->
                vault.save(SavedDevice(trust,tokens(),clock[0]+3600000)); api.identityFailure=IOException()
                check(manager.check().state==PairingState.OFFLINE && vault.value!=null && api.refreshes==0)
            } }
            test("TLS failure never triggers refresh") { fixture { manager,vault,api,clock ->
                vault.save(SavedDevice(trust,tokens(),clock[0]+3600000)); api.identityFailure=SSLHandshakeException("test")
                check(manager.check().state==PairingState.SECURITY_ERROR && api.refreshes==0)
            } }
            test("durable rotation intent precedes refresh network request") { fixture { manager,vault,api,clock ->
                vault.save(SavedDevice(trust,tokens(),clock[0]+3600000)); api.expires=true
                api.refreshAction={ check(vault.value!!.refreshPending); api.current=tokens("b");api.expires=false;api.current }
                check(manager.check().state==PairingState.ASSOCIATED && !vault.value!!.refreshPending)
            } }
            test("process restart with interrupted refresh never replays the secret") { fixture { manager,vault,api,clock ->
                vault.save(SavedDevice(trust,tokens(),clock[0]+3600000,true))
                check(manager.check().state==PairingState.REASSOCIATE && vault.value==null && api.refreshes==0)
            } }
            test("ambiguous refresh erases old credentials without retry") { fixture { manager,vault,api,clock ->
                vault.save(SavedDevice(trust,tokens(),clock[0]+3600000)); api.expires=true;api.refreshAction={throw IOException()}
                check(manager.check().state==PairingState.REASSOCIATE && vault.value==null)
                manager.check(); check(api.refreshes==1)
            } }
            test("write failure stops refresh before sending credentials") { fixture { manager,vault,api,clock ->
                vault.save(SavedDevice(trust,tokens(),clock[0]+3600000)); api.expires=true;vault.failWrite=true
                rejects { manager.check() }; check(api.refreshes==0)
            } }
            test("revocation clears stored device credentials") { fixture { manager,vault,api,clock ->
                vault.save(SavedDevice(trust,tokens(),clock[0]+3600000));api.expires=true
                api.refreshAction={throw DeviceApiFailure(401,"invalid_grant")}
                check(manager.check().state==PairingState.REASSOCIATE && vault.value==null)
            } }
            test("concurrent callers only rotate once") { fixture { manager,vault,api,clock ->
                vault.save(SavedDevice(trust,tokens(),clock[0]+3600000));api.expires=true
                val pool=Executors.newFixedThreadPool(2)
                try { val results=(1..2).map { pool.submit<PairingView> { manager.check() } }
                    check(results.all { it.get().state==PairingState.ASSOCIATED });check(api.refreshes==1)
                } finally { pool.shutdownNow() }
            } }
            test("refresh cannot extend the absolute session deadline") { fixture { manager,vault,api,clock ->
                val deadline=clock[0]+60000;vault.save(SavedDevice(trust,tokens(),deadline));api.expires=true
                check(manager.check().state==PairingState.ASSOCIATED && vault.value!!.refreshDeadline==deadline)
            } }
            test("forget removes local state even if logout fails") { fixture { manager,vault,_,clock ->
                vault.save(SavedDevice(trust,tokens(),clock[0]+3600000));manager.forget();check(vault.value==null)
            } }
            test("Directory proof binds the saved account after polling") { fixture { manager,vault,api,clock ->
                api.descriptor=api.descriptor.copy(accountId=DEVICE)
                manager.begin(trust,"TV","signed-fixture",DEVICE);clock[0]+=5000
                check(manager.poll().state==PairingState.ASSOCIATED && vault.value!!.accountId==DEVICE && api.assertions==1)
            } }
            test("Directory account mismatch erases the association") { fixture { manager,vault,api,clock ->
                manager.begin(trust,"TV","signed-fixture",DEVICE);clock[0]+=5000
                check(manager.poll().state==PairingState.SECURITY_ERROR && vault.value==null && api.refreshes==0)
            } }
            test("refresh retains the bound account") { fixture { manager,vault,api,clock ->
                api.descriptor=api.descriptor.copy(accountId=DEVICE);api.expires=true
                vault.save(SavedDevice(trust,tokens(),clock[0]+3600000,accountId=DEVICE))
                check(manager.check().state==PairingState.ASSOCIATED && vault.value!!.accountId==DEVICE)
            } }
            test("certificate update cannot move account server or origin") { fixture { manager,vault,_,clock ->
                vault.save(SavedDevice(trust,tokens(),clock[0]+3600000,accountId=DEVICE))
                rejects { manager.updateTrust(trust,SERVER) }
                rejects { manager.updateTrust(ServerTrust(ORIGIN,DEVICE,trust.certificateDer),DEVICE) }
                rejects { manager.updateTrust(ServerTrust("https://127.0.0.1:8921",SERVER,trust.certificateDer),DEVICE) }
                manager.updateTrust(trust,DEVICE);check(vault.value!!.tokens.deviceId==DEVICE)
            } }
            test("account and signed assertion are required together") { fixture { manager,_,api,_ ->
                rejects { manager.begin(trust,"TV",accountId=DEVICE) }
                rejects { manager.begin(trust,"TV",assertion="signed-fixture") }
                check(api.assertions==0)
            } }
            tlsTest(trust,keystore)
        } finally {
            Files.deleteIfExists(certificate);Files.deleteIfExists(keystore);Files.deleteIfExists(directory)
        }
        return count
    }

    private fun tlsTest(trust: ServerTrust, path: Path) {
        val password="temporary-test-password".toCharArray()
        val keys=KeyStore.getInstance("PKCS12").apply { Files.newInputStream(path).use { load(it,password) } }
        val keyManagers=KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm()).apply { init(keys,password) }
        val tls=SSLContext.getInstance("TLS").apply { init(keyManagers.keyManagers,null,null) }
        val server=HttpsServer.create(InetSocketAddress("127.0.0.1",0),0)
        server.httpsConfigurator=HttpsConfigurator(tls)
        server.createContext("/") { exchange -> exchange.sendResponseHeaders(200,2);exchange.responseBody.use { it.write("ok".toByteArray()) } }
        server.start()
        try {
            fun request(host: String, pinned: Boolean): Int {
                val connection=URL("https://$host:${server.address.port}/").openConnection() as HttpsURLConnection
                connection.connectTimeout=3000;connection.readTimeout=3000
                if(pinned) connection.sslSocketFactory=PinnedServerTls.socketFactory(trust)
                return try { connection.responseCode } finally { connection.disconnect() }
            }
            test("real TLS owner-confirmed certificate accepted") { check(request("127.0.0.1",true)==200) }
            test("real TLS wrong hostname refused despite valid certificate pin") { rejectsTls { request("localhost",true) } }
            test("real TLS unknown certificate refused by default trust") { rejectsTls { request("127.0.0.1",false) } }
        } finally { server.stop(0) }
    }
}
