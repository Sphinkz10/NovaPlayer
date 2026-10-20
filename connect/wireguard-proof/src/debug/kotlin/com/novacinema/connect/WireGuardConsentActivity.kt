package com.novacinema.connect

import android.app.Activity
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import android.widget.Button

/** Disposable proof only. The real Android VPN permission dialog is mandatory. */
class WireGuardConsentActivity : Activity() {
    @Volatile var answered = false
    @Volatile var approved = false
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        setContentView(Button(this).apply {
            text = "Autorizar VPN do ensaio"
            setOnClickListener {
                val consent = VpnService.prepare(this@WireGuardConsentActivity)
                if (consent == null) { approved = true; answered = true }
                else startActivityForResult(consent, 41)
            }
        })
    }
    @Deprecated("Disposable consent proof")
    override fun onActivityResult(request: Int, result: Int, data: Intent?) {
        super.onActivityResult(request, result, data)
        if (request == 41) { approved = result == RESULT_OK; answered = true }
    }
}
