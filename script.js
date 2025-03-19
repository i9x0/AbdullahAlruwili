
document.addEventListener("DOMContentLoaded", () => {
    const name = "Abdullah Alrwuili"; 
    const GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$%^&*";
    const textElement = document.getElementById("animated-text"); 
    let iteration = -1; 

    function startEffect() {
        iteration = -1;
        const interval = setInterval(() => {
            textElement.innerText = name
                .split("")
                .map((char, index) => 
                    index <= iteration ? char : GLYPHS[Math.floor(Math.random() * GLYPHS.length)]
                )
                .join("");

            iteration++; 

            if (iteration > name.length) { 
                clearInterval(interval);
                setTimeout(startEffect, 2000);
            }
        }, 100);
    }

    startEffect();
    particlesJS("pr", {
        particles: {
            number: { value: 100, density: { enable: true, value_area: 800 } },
            color: { value: "#ffffff" },
            shape: { type: "circle" },
            opacity: { value: 0.5, random: false },
            size: { value: 3, random: true },
            move: { enable: true, speed: 2, direction: "none", random: false },
            line_linked: { color: "#ffffff" } 
        },
        interactivity: {
            events: {
                onhover: { enable: true, mode: "grab" },
                onclick: { enable: true, mode: "push" }
            }
        }}
    );
});
