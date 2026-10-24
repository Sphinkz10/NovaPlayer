package com.novacinema.connect;

/** JVM boundary checks for provider scope. No Android SDK/runtime or network needed. */
public final class TailscalePolicyChecks {
    private static int checks;
    private static void expect(boolean condition) {
        if (!condition) throw new AssertionError("Tailscale route boundary failed at check " + (checks + 1));
        checks++;
    }
    private static void refused(Runnable action) {
        boolean failed = false;
        try { action.run(); } catch (IllegalArgumentException | IllegalStateException expected) { failed = true; }
        expect(failed);
    }
    public static void main(String[] args) {
        var api = TailscaleRoutePolicy.Companion;
        for (String address : new String[] {"100.64.0.0", "100.64.0.1", "100.100.100.100", "100.127.255.255"})
            expect(api.isOverlayV4(address));
        for (String address : new String[] {"100.63.255.255", "100.128.0.0", "10.0.0.1", "192.168.1.1", "127.0.0.1",
                "8.8.8.8", "100.064.0.1", "100.64.0.256", "100.64.0.-1", "100.64.0.1.", "100.64.0.1/32", "host.invalid"})
            expect(!api.isOverlayV4(address));
        expect(api.isOverlayV6("fd7a:115c:a1e0::1"));
        expect(!api.isOverlayV6("fd7a:115c:a1e1::1"));
        expect(!api.isOverlayV6("::1"));
        expect(!api.isOverlayV6("host.invalid"));
        refused(() -> new TailscaleRoutePolicy("10.0.0.1"));
        refused(() -> new TailscaleRoutePolicy("100.64.0.1").ready());
        for (String route : new String[] {"0.0.0.0", "10.0.0.0", "192.168.0.0", "8.8.8.8"})
            refused(() -> new TailscaleRoutePolicy("100.64.0.1").route(route, 0));
        refused(() -> new TailscaleRoutePolicy("100.64.0.1").route("100.64.0.0", 9));
        refused(() -> new TailscaleRoutePolicy("100.64.0.1").route("100.64.0.0", 33));
        var broad = new TailscaleRoutePolicy("100.64.0.1"); broad.route("100.64.0.0", 10); broad.ready(); checks++;
        var other = new TailscaleRoutePolicy("100.64.0.1"); other.route("100.64.0.2", 32); refused(other::ready);
        var exact = new TailscaleRoutePolicy("100.64.0.1"); exact.route("100.64.0.1", 32); exact.ready(); checks++;
        exact.exclude("10.0.0.0", 8); exact.ready(); checks++;
        exact.exclude("100.64.0.1", 32); refused(exact::ready);
        var excluded = new TailscaleRoutePolicy("100.64.0.1"); excluded.route("100.64.0.0", 10);
        excluded.exclude("0.0.0.0", 0); refused(excluded::ready);
        expect(api.controlOrigin("https://controlplane.tailscale.com").equals("https://controlplane.tailscale.com"));
        expect(api.controlOrigin("https://10.0.2.2:18443").equals("https://10.0.2.2:18443"));
        for (String url : new String[] {"http://control.invalid", "https://control.invalid/path", "https://user@control.invalid",
                "https://control.invalid?secret", "https://control.invalid#fragment", "https://control.invalid:0"})
            refused(() -> api.controlOrigin(url));
        System.out.println("PASS: " + checks + " Tailscale provider boundary checks");
    }
}
