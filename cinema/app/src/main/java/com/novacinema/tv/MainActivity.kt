package com.novacinema.tv

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.min

/**
 * Signature / SIG-01 Home from Figma node 69:3.
 * Visual prototype only: no credentials, Jellyfin calls, player or VPN included.
 * The Figma hero and card art are local PNG exports of artwork-only nodes.
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { SignatureHome() }
    }
}

private val background = Color(0xFF080C17)
private val raised = Color(0xFF293B57)
private val active = Color(0xFF273550)
private val focusColor = Color(0xFFC9D6FF)
private val primary = Color(0xFFDEE7FF)
private val textPrimary = Color(0xFFFBFAFF)
private val textSecondary = Color(0xFFC4CDE0)

private fun pos(s: Float, x: Int, y: Int, w: Int, h: Int): Modifier =
    Modifier.offset((x * s).dp, (y * s).dp).size((w * s).dp, (h * s).dp)

@Composable
private fun T(
    value: String, s: Float, x: Int, y: Int, w: Int, h: Int,
    size: Int, weight: FontWeight = FontWeight.Normal,
    color: Color = textPrimary
) {
    Text(
        text = value,
        modifier = pos(s, x, y, w, h),
        fontSize = (size * s).sp,
        lineHeight = (size * 1.18f * s).sp,
        color = color,
        fontWeight = weight,
        maxLines = 2,
        overflow = TextOverflow.Ellipsis
    )
}

@Composable
private fun FocusTile(
    s: Float,
    x: Int, y: Int, w: Int, h: Int,
    fill: Color,
    selected: Boolean = false,
    radius: Int = 16,
    onClick: () -> Unit,
    content: @Composable () -> Unit
) {
    var focused by remember { mutableStateOf(false) }
    val shape = RoundedCornerShape((radius * s).dp)
    Box(
        modifier = pos(s, x, y, w, h)
            .clip(shape)
            .background(if (focused) active else fill)
            .then(if (focused || selected) Modifier.border((3 * s).dp, focusColor, shape) else Modifier)
            .onFocusChanged { focused = it.isFocused }
            .clickable(onClick = onClick)
            .focusable(),
        contentAlignment = Alignment.CenterStart
    ) { content() }
}

@Composable
private fun NavItem(label: String, s: Float, x: Int, w: Int, selected: Boolean, onClick: () -> Unit) {
    FocusTile(s, x, 59, w, 47, if (selected) active else Color.Transparent, false, 14, onClick) {
        Text(
            text = label,
            modifier = Modifier.padding(start = (17 * s).dp),
            fontSize = (20 * s).sp,
            color = if (selected) textPrimary else Color(0xFFC4C7D9),
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Medium
        )
    }
}

@Composable
private fun Action(s: Float, x: Int, width: Int, title: String, principal: Boolean, onClick: () -> Unit) {
    FocusTile(
        s = s, x = x, y = 603, w = width, h = 70,
        fill = if (principal) primary else raised, selected = principal,
        onClick = onClick
    ) {
        Text(
            text = title,
            modifier = Modifier.padding(horizontal = (20 * s).dp),
            fontSize = (22 * s).sp,
            fontWeight = FontWeight.SemiBold,
            color = if (principal) Color(0xFF101B2D) else textPrimary,
            maxLines = 1
        )
    }
}

@Composable
private fun MediaCard(
    s: Float, x: Int, title: String, meta: String, art: Int,
    focusedInitially: Boolean = false, onClick: () -> Unit
) {
    var focused by remember { mutableStateOf(false) }
    val shape = RoundedCornerShape((18 * s).dp)
    Box(
        modifier = pos(s, x, 814, 336, 216)
            .clip(shape)
            .background(Color(0xFF161E31))
            .then(if (focused || focusedInitially) Modifier.border((3 * s).dp, focusColor, shape) else Modifier)
            .onFocusChanged { focused = it.isFocused }
            .clickable(onClick = onClick)
            .focusable()
    ) {
        Image(
            painter = painterResource(art),
            contentDescription = null,
            contentScale = ContentScale.FillBounds,
            modifier = pos(s, 0, 0, 336, 132)
        )
        Box(modifier = pos(s, 0, 132, 336, 84).background(Color(0xFF151C2C)))
        T(title, s, 18, 143, 307, 31, 21, FontWeight.SemiBold)
        T(meta, s, 19, 173, 305, 27, 18, color = Color(0xFFC2C9DF))
    }
}

@Composable
private fun SignatureHome() {
    var note by remember { mutableStateOf<String?>(null) }
    var selectedNav by remember { mutableStateOf("Início") }

    BoxWithConstraints(Modifier.background(background)) {
        val s = min(maxWidth.value / 1920f, maxHeight.value / 1080f)
        val screenW = (1920 * s).dp
        val screenH = (1080 * s).dp
        Box(Modifier.size(screenW, screenH).align(Alignment.Center)) {
            Image(
                painter = painterResource(R.drawable.nova_hero),
                contentDescription = null,
                modifier = pos(s, 0, 0, 1920, 758),
                contentScale = ContentScale.FillBounds
            )

            T("✦", s, 85, 56, 50, 42, 29, FontWeight.Bold, Color(0xFFBECDFC))
            T("NOVA", s, 130, 59, 160, 45, 28, FontWeight.Bold, Color(0xFFF8F9FF))
            NavItem("Início", s, 350, 109, selectedNav == "Início") { selectedNav = "Início" }
            NavItem("Filmes", s, 506, 106, selectedNav == "Filmes") { note = "Filmes: vista a integrar com o NOVA Server." }
            NavItem("Séries", s, 640, 104, selectedNav == "Séries") { note = "Séries: vista a integrar com o NOVA Server." }
            NavItem("Descobrir", s, 773, 143, selectedNav == "Descobrir") { note = "Descobrir: vista Signature por implementar." }
            NavItem("Minha Lista", s, 950, 158, selectedNav == "Minha Lista") { note = "Minha Lista: sincronização por utilizador pendente." }

            T("⌕", s, 1543, 67, 60, 43, 28, FontWeight.SemiBold)
            T("⚙", s, 1639, 67, 60, 43, 25, FontWeight.Medium, Color(0xFFB8C3D8))
            Box(modifier = pos(s, 1756, 55, 56, 56)
                .clip(RoundedCornerShape((28 * s).dp))
                .background(Color(0xFF36435F)))
            T("R", s, 1776, 66, 29, 40, 24, FontWeight.Bold)

            Box(modifier = pos(s, 95, 210, 364, 36)
                .clip(RoundedCornerShape((13 * s).dp))
                .background(Color(0xFF222B43)))
            T("EM DESTAQUE  /  DA TUA BIBLIOTECA", s, 110, 218, 345, 25, 18,
                FontWeight.SemiBold, Color(0xFFC1CFFF))
            T("DEPOIS DAS", s, 95, 274, 815, 120, 84, FontWeight.Bold)
            T("ESTRELAS", s, 95, 375, 885, 143, 101, FontWeight.Bold)
            T("Uma história à espera do play.", s, 99, 490, 737, 39, 25,
                FontWeight.Medium, Color(0xFFD2D6E6))
            T("2026  ·  Ficção científica  ·  1h 54m", s, 99, 542, 799, 34, 21,
                FontWeight.Medium, Color(0xFFC6CDDF))
            Action(s, 95, 263, "▶  Reproduzir", true) {
                note = "A reprodução real estará disponível após ligar a NOVA Cinema ao NOVA Server."
            }
            Action(s, 375, 265, "Mais informações", false) {
                note = "Ficha de Depois das Estrelas: ecrã Signature ainda por integrar."
            }

            Box(modifier = pos(s, 0, 726, 1920, 354).background(background))
            T("A SEGUIR", s, 95, 763, 400, 40, 26, FontWeight.SemiBold)
            T("Ver tudo   →", s, 1699, 767, 175, 32, 19, FontWeight.Medium, Color(0xFFBECBFF))

            MediaCard(s, 95, "Horizonte Zero", "T02 E04 · 32 min",
                R.drawable.nova_horizonte_zero, true) { note = "Horizonte Zero: reprodução ainda indisponível." }
            MediaCard(s, 452, "Terras de Sal", "Filme · 1h 47m",
                R.drawable.nova_terras_de_sal) { note = "Terras de Sal: detalhe por integrar." }
            MediaCard(s, 808, "Cidade sem Sono", "Filme · 1h 42m",
                R.drawable.nova_cidade_sem_sono) { note = "Cidade sem Sono: detalhe por integrar." }

            FocusTile(s, 1165, 814, 661, 216,
                Color(0xFF1B2745), radius = 18,
                onClick = { note = "NOVA Smart Pick: sugestões ainda não implementadas." }) {
                Box(Modifier.size((661 * s).dp, (216 * s).dp)
                    .background(Brush.horizontalGradient(
                        listOf(Color(0xFF1B2745), Color(0xFF3D3456)))))
                Image(
                    painter = painterResource(R.drawable.nova_smart_orbit),
                    contentDescription = null,
                    modifier = pos(s, 511, -91, 228, 228),
                    contentScale = ContentScale.FillBounds
                )
                T("✦   ESCOLHE POR MIM", s, 29, 24, 580, 31, 18,
                    FontWeight.SemiBold, Color(0xFFC6D4FF))
                T("O que vamos ver?", s, 29, 75, 600, 52, 32, FontWeight.Bold)
                T("Até 120 min   ·   Surpreende-me   ·   Não vistos", s, 29, 132, 605, 32, 19,
                    color = Color(0xFFD0CDE3))
                T("Explorar sugestões    →", s, 30, 174, 611, 31, 19,
                    FontWeight.SemiBold, Color(0xFFD5DAFF))
            }
            if (note != null) {
                Box(
                    modifier = pos(s, 570, 680, 790, 98)
                        .clip(RoundedCornerShape((18 * s).dp))
                        .background(Color(0xFF293B57))
                        .clickable { note = null },
                    contentAlignment = Alignment.Center
                ) {
                    Text(note.orEmpty(), color = textPrimary,
                        fontSize = (23 * s).sp, maxLines = 2,
                        modifier = Modifier.padding((18 * s).dp))
                }
            }
        }
    }
}
