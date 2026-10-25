package com.novacinema.connect

import android.app.Activity
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import android.widget.Button

class TailscaleConsentActivity : Activity() {
    companion object { @Volatile var approved = false }
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        setContentView(Button(this).apply {
            text = "Autorizar Tailscale do ensaio"
            setOnClickListener {
                val intent = VpnService.prepare(this@TailscaleConsentActivity)
                if (intent == null) approved = true else startActivityForResult(intent, 42)
            }
        })
    }
    @Deprecated("Disposable consent proof")
    override fun onActivityResult(request: Int, result: Int, data: Intent?) {
        super.onActivityResult(request, result, data)
        if (request == 42) approved = result == RESULT_OK
    }
}
