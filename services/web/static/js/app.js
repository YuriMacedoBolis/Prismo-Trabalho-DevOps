/* =============================================================================
   Prismo — animacoes (Fase 1)

   Tres principios:
     1. O conteudo nunca depende da animacao. Se o GSAP nao carregar, tudo
        aparece normalmente (fallback no final do arquivo).
     2. prefers-reduced-motion desliga tudo. E acessibilidade, nao enfeite.
     3. Animamos apenas `transform` e `opacity`, que a GPU resolve sem
        recalcular layout. Animar `top`/`height` causaria travamento.
   ========================================================================== */

(function () {
  "use strict";

  const reduzirMovimento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---- Troca de tema ---------------------------------------------------- */

  function aplicarTema(tema) {
    document.documentElement.setAttribute("data-theme", tema);
    document.querySelectorAll("[data-theme-set]").forEach((botao) => {
      botao.setAttribute("aria-pressed", String(botao.dataset.themeSet === tema));
    });
    // localStorage pode lancar excecao em janela privada ou com cookies
    // bloqueados, e a pagina precisa funcionar nesses casos.
    try {
      localStorage.setItem("prismo:tema", tema);
    } catch (_) { /* preferencia nao persistida, sem prejuizo */ }
  }

  function iniciarTemas() {
    let salvo = null;
    try {
      salvo = localStorage.getItem("prismo:tema");
    } catch (_) { /* ignorado */ }

    if (salvo) aplicarTema(salvo);

    document.querySelectorAll("[data-theme-set]").forEach((botao) => {
      botao.addEventListener("click", () => aplicarTema(botao.dataset.themeSet));
    });
  }

  /* ---- Brilho que segue o cursor nos cards ------------------------------ */

  function iniciarBrilho() {
    if (reduzirMovimento) return;

    document.querySelectorAll(".card").forEach((card) => {
      card.addEventListener("mousemove", (evento) => {
        const caixa = card.getBoundingClientRect();
        card.style.setProperty("--mx", `${evento.clientX - caixa.left}px`);
        card.style.setProperty("--my", `${evento.clientY - caixa.top}px`);
      });
    });
  }

  /* ---- Efeito magnetico nos botoes ------------------------------------- */

  function iniciarMagnetico() {
    // Em telas de toque nao existe cursor para seguir, e o efeito so
    // atrapalharia o toque.
    if (reduzirMovimento || !window.matchMedia("(hover: hover)").matches) return;

    document.querySelectorAll("[data-magnetic]").forEach((alvo) => {
      alvo.addEventListener("mousemove", (evento) => {
        const caixa = alvo.getBoundingClientRect();
        const dx = (evento.clientX - (caixa.left + caixa.width / 2)) * 0.18;
        const dy = (evento.clientY - (caixa.top + caixa.height / 2)) * 0.28;
        alvo.style.transform = `translate(${dx}px, ${dy}px)`;
      });
      alvo.addEventListener("mouseleave", () => {
        alvo.style.transform = "";
      });
    });
  }

  /* ---- Animacoes de entrada (GSAP) ------------------------------------- */

  function iniciarAnimacoes() {
    if (typeof window.gsap === "undefined") return false;

    const gsap = window.gsap;
    if (window.ScrollTrigger) gsap.registerPlugin(window.ScrollTrigger);

    document.documentElement.classList.add("anims-ready");

    // Revelacao do titulo palavra por palavra. Quebramos o texto em <span>
    // para poder atrasar cada palavra: o atraso progressivo e o que cria a
    // sensacao de leitura, em vez de um bloco inteiro surgindo de uma vez.
    document.querySelectorAll('[data-anim="reveal"]').forEach((elemento) => {
      const palavras = elemento.textContent.trim().split(/\s+/);
      elemento.innerHTML = palavras
        .map((p) => `<span class="word">${p}</span>`)
        .join(" ");

      gsap.from(elemento.querySelectorAll(".word"), {
        yPercent: 110,
        opacity: 0,
        duration: 0.85,
        ease: "power3.out",
        stagger: 0.045,
      });
    });

    document.querySelectorAll('[data-anim="fade"]').forEach((elemento) => {
      gsap.from(elemento, {
        y: 18,
        opacity: 0,
        duration: 0.7,
        ease: "power2.out",
        delay: parseFloat(elemento.dataset.delay || "0.1"),
      });
    });

    // Elementos abaixo da dobra entram conforme o scroll chega neles.
    const subindo = document.querySelectorAll('[data-anim="rise"]');
    if (window.ScrollTrigger && subindo.length) {
      subindo.forEach((elemento) => {
        gsap.from(elemento, {
          y: 42,
          opacity: 0,
          duration: 0.75,
          ease: "power2.out",
          scrollTrigger: {
            trigger: elemento,
            start: "top 88%",
            once: true,
          },
        });
      });
    } else {
      gsap.from(subindo, { y: 42, opacity: 0, duration: 0.75, stagger: 0.07 });
    }

    return true;
  }

  /* ---- Inicializacao --------------------------------------------------- */

  function iniciar() {
    iniciarTemas();
    iniciarBrilho();
    iniciarMagnetico();

    if (reduzirMovimento) {
      document.documentElement.classList.add("anims-ready");
      return;
    }

    // Os scripts do CDN tem `defer`, entao podem nao estar prontos ainda.
    // Tentamos algumas vezes e, se o CDN falhar, mostramos tudo sem animacao.
    let tentativas = 0;
    (function tentar() {
      if (iniciarAnimacoes()) return;
      if (++tentativas > 25) {
        document.documentElement.classList.add("no-js");
        return;
      }
      setTimeout(tentar, 60);
    })();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }
})();
