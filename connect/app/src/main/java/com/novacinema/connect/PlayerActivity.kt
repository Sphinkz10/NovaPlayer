package com.novacinema.connect

import android.app.Activity
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.WindowManager
import android.widget.*
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.datasource.DataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.ui.PlayerView
import androidx.media3.ui.TrackSelectionDialogBuilder
import java.util.concurrent.Executors

/** Foreground playback only. Stop releases codecs, connections and the display wake lock. */
@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
class PlayerActivity:Activity() {
    private val io=Executors.newSingleThreadExecutor()
    private val handler=Handler(Looper.getMainLooper())
    private var player:ExoPlayer?=null
    private lateinit var view:PlayerView
    private lateinit var status:TextView
    private lateinit var library:String
    private lateinit var item:String
    private var position=0L
    private var playWhenReady=true
    private var runtimeMillis=0L
    private var completed=false
    internal val observedPlaying:Boolean get()=player?.isPlaying==true
    private var generation=0
    private var foreground=false
    private var eventBusy=false
    internal var renderedFrame=false
        private set
    internal val observedPosition:Long get()=player?.currentPosition ?: position
    private val heartbeat=object:Runnable {
        override fun run() {
            if(!foreground)return
            val p=player ?: return
            report("progress",p.currentPosition,!p.isPlaying)
            handler.postDelayed(this,10000)
        }
    }
    override fun onCreate(state:Bundle?) {
        super.onCreate(state);window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        library=intent.getStringExtra("library").orEmpty();item=intent.getStringExtra("item").orEmpty()
        if(!mediaId.matches(library) || !mediaId.matches(item)) { finish();return }
        position=state?.getLong("position") ?: intent.getLongExtra("position",0).coerceAtLeast(0)
        playWhenReady=state?.getBoolean("playing",true) ?: true
        window.decorView.systemUiVisibility=android.view.View.SYSTEM_UI_FLAG_FULLSCREEN or
            android.view.View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or android.view.View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        val root=FrameLayout(this).apply { setBackgroundColor(android.graphics.Color.BLACK) }
        view=PlayerView(this).apply { useController=true;controllerShowTimeoutMs=5000 }
        root.addView(view,FrameLayout.LayoutParams(-1,-1))
        val controls=LinearLayout(this).apply {
            orientation=LinearLayout.HORIZONTAL;gravity=android.view.Gravity.CENTER_VERTICAL
            setPadding(TvUi.dp(context,18),TvUi.dp(context,6),TvUi.dp(context,18),TvUi.dp(context,6))
            setBackgroundColor(0xdd090f1b.toInt())
        }
        status=TextView(this).apply { textSize=15f;setTextColor(TvUi.ink) }
        controls.addView(status,LinearLayout.LayoutParams(0,-2,2f))
        fun button(title:String,tagValue:String,action:()->Unit)=TvUi.button(controls,title,tagValue,action)
        button("Áudio","player-audio") {
            player?.let { TrackSelectionDialogBuilder(this,"Áudio",it,androidx.media3.common.C.TRACK_TYPE_AUDIO).build().show() }
        }
        button("Legendas","player-subtitles") {
            player?.let { TrackSelectionDialogBuilder(this,"Legendas",it,androidx.media3.common.C.TRACK_TYPE_TEXT).build().show() }
        }
        button("Repetir","player-retry") { if(completed)position=0;playWhenReady=true;open() }
        button("Voltar","player-back") { finish() }
        root.addView(controls,FrameLayout.LayoutParams(-1,-2,android.view.Gravity.TOP))
        view.setControllerVisibilityListener(PlayerView.ControllerVisibilityListener { visibility -> controls.visibility=visibility })
        setContentView(root);view.requestFocus()
    }
    override fun onStart() { super.onStart();foreground=true;if(::view.isInitialized)open() }
    override fun onSaveInstanceState(out:Bundle) { out.putLong("position",observedPosition);out.putBoolean("playing",player?.playWhenReady ?: playWhenReady);super.onSaveInstanceState(out) }
    override fun onStop() {
        foreground=false;generation++;handler.removeCallbacks(heartbeat)
        player?.let { position=it.currentPosition;playWhenReady=it.playWhenReady;report("stop",position,true,final=true) }
        release();super.onStop()
    }
    override fun onDestroy() { io.shutdown();super.onDestroy() }
    private fun release() {
        if(::view.isInitialized) { view.player=null;view.keepScreenOn=false }
        player?.release();player=null
    }
    private fun open() {
        handler.removeCallbacks(heartbeat)
        player?.let { if(!completed)position=it.currentPosition };release();renderedFrame=false;completed=false
        status.text="A verificar título e autorização…";val current=++generation;val requestedPosition=position
        io.execute {
            val ready=runCatching {
                val client=MediaClient(this);val detail=client.detail(library,item)
                runtimeMillis=detail.runtime/10000
                val resolved=if(detail.runtime>0)requestedPosition.coerceAtMost(detail.runtime/10000) else requestedPosition
                client.event(library,item,"start",resolved,!playWhenReady)
                client.session().trust.origin to resolved
            }
            runOnUiThread {
                if(!foreground || current!=generation || isDestroyed)return@runOnUiThread
                ready.fold({ (origin,resolved) ->
                    position=resolved
                    val p=ExoPlayer.Builder(this).build();player=p;view.player=p;view.keepScreenOn=true
                    val source=ProgressiveMediaSource.Factory(DataSource.Factory { NovaMediaSource(this) })
                        .createMediaSource(MediaItem.fromUri("$origin/api/v1/media/libraries/$library/items/$item/stream"))
                    p.addListener(object:Player.Listener {
                        override fun onIsPlayingChanged(isPlaying:Boolean) { view.keepScreenOn=isPlaying }
                        override fun onPlayWhenReadyChanged(value:Boolean,reason:Int) {
                            playWhenReady=value
                            if(renderedFrame && foreground)report("progress",p.currentPosition,!value)
                        }
                        override fun onRenderedFirstFrame() { renderedFrame=true;status.text="Qualidade original · "+TvUi.network(this@PlayerActivity) }
                        override fun onPlayerError(error:PlaybackException) {
                            status.text="Reprodução interrompida. Verifica a ligação e usa Repetir. Se o formato não for suportado, experimenta outro ficheiro."
                            view.keepScreenOn=false;view.showController()
                        }
                        override fun onPlaybackStateChanged(state:Int) {
                            if(state==Player.STATE_ENDED) { completed=true;handler.removeCallbacks(heartbeat)
                                report("stop",p.duration.coerceAtLeast(0),true);view.keepScreenOn=false
                                status.text="Terminou. Podes voltar aos títulos ou repetir.";view.showController() }
                        }
                    })
                    p.setMediaSource(source);p.seekTo(position);p.prepare();p.playWhenReady=playWhenReady
                    handler.postDelayed(heartbeat,10000)
                },{ status.text="Não foi possível autorizar este título. Verifica a conta, o servidor e a ligação." })
            }
        }
    }
    private fun report(event:String,millis:Long,paused:Boolean,final:Boolean=false) {
        if(eventBusy && !final)return
        eventBusy=true;val current=generation
        io.execute {
            val success=runCatching { MediaClient(this).event(library,item,event,if(runtimeMillis>0)millis.coerceIn(0,runtimeMillis) else millis.coerceAtLeast(0),paused) }.isSuccess
            runOnUiThread {
                eventBusy=false
                if(!final && foreground && current==generation && !success) {
                    position=observedPosition;handler.removeCallbacks(heartbeat);release()
                    status.text="Ligação ou autorização indisponível. Verifica a rede e usa Repetir.";view.showController()
                }
            }
        }
    }
    override fun dispatchKeyEvent(event:android.view.KeyEvent):Boolean =
        if(::view.isInitialized && (view.hasFocus() || event.keyCode in setOf(85,86,87,88,89,90,126,127)) && view.dispatchKeyEvent(event))true else super.dispatchKeyEvent(event)
}
