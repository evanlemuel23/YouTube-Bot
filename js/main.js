// page transition
window.addEventListener('DOMContentLoaded', ()=>{
    document.body.classList.add('loaded');
});

// hamburger
const hamburger = document.querySelector('.hamburger');
const sidebar = document.querySelector('.sidebar');
hamburger.addEventListener('click', () => {
    sidebar.classList.toggle('open');
});

// intersection observer for fade-slide
const observer = new IntersectionObserver((entries)=>{
    entries.forEach(entry=>{
        if(entry.isIntersecting){
            entry.target.classList.add('visible');
            observer.unobserve(entry.target);
        }
    });
},{threshold:0.2});

// hero reveal animation
window.addEventListener('load',()=>{
    const badge = document.querySelector('.hero .badge');
    const title = document.querySelector('.hero-title');
    if(badge) badge.style.opacity = '1', badge.style.transform = 'translateY(0)';
    if(title) title.style.opacity = '1', title.style.transform = 'translateY(0)';
    // simple glitch/typewriter effect for title
    if(title){
        const text = title.textContent;
        let i=0;
        title.textContent='';
        const interval = setInterval(()=>{
            title.textContent += text[i];
            i++;
            if(i>=text.length) clearInterval(interval);
        },100);
    }
});

document.querySelectorAll('section, .card, .dept-card, .testimonial, .btn').forEach(el=>{
    el.classList.add('fade-slide');
    observer.observe(el);
});

// count up stats
const stats = document.querySelectorAll('.stat[data-target]');
const statObserver = new IntersectionObserver((entries)=>{
    entries.forEach(entry =>{
        if(entry.isIntersecting){
            const el = entry.target;
            const target = parseInt(el.getAttribute('data-target'));
            if(!isNaN(target)){
                let count = 0;
                const step = () =>{
                    count += Math.ceil(target / 100);
                    if(count < target){
                        el.textContent = count + (el.textContent.includes('%')?'%+':'+');
                        requestAnimationFrame(step);
                    } else {
                        el.textContent = target + (el.textContent.includes('%')?'%+':'+');
                    }
                };
                step();
            }
            statObserver.unobserve(el);
        }
    });
},{threshold:0.5});
stats.forEach(s=>statObserver.observe(s));

// cursor glow
const cursorDot = document.createElement('div');
const cursorRing = document.createElement('div');
cursorDot.className = 'cursor-dot';
cursorRing.className = 'cursor-ring';
document.body.appendChild(cursorDot);
document.body.appendChild(cursorRing);

let mouseX=0, mouseY=0;
window.addEventListener('mousemove', (e)=>{
    mouseX=e.clientX;
    mouseY=e.clientY;
    cursorDot.style.transform = `translate(${mouseX}px,${mouseY}px)`;
    cursorRing.style.transform = `translate(${mouseX}px,${mouseY}px)`;
});

document.querySelectorAll('a, button').forEach(el=>{
    el.addEventListener('mouseenter', ()=>{
        cursorRing.classList.add('hover');
    });
    el.addEventListener('mouseleave', ()=>{
        cursorRing.classList.remove('hover');
    });
});

// magnetic buttons
const magnetic = document.querySelectorAll('.magnetic');
magnetic.forEach(btn=>{
    btn.addEventListener('mousemove', (e)=>{
        const rect = btn.getBoundingClientRect();
        const x = e.clientX - rect.left - rect.width/2;
        const y = e.clientY - rect.top - rect.height/2;
        btn.style.transform = `translate(${x*0.2}px,${y*0.2}px)`;
    });
    btn.addEventListener('mouseleave', ()=>{
        btn.style.transform='';
    });
});

// particles canvas
const canvas = document.getElementById('particle-canvas');
const ctx = canvas.getContext('2d');
let particles = [];
function initParticles(){
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    particles = [];
    for(let i=0;i<100;i++){
        particles.push({
            x: Math.random()*canvas.width,
            y: Math.random()*canvas.height,
            r: Math.random()*2+1,
            vx: (Math.random()-0.5)*0.2,
            vy: (Math.random()-0.5)*0.2
        });
    }
}
function drawParticles(){
    ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.fillStyle = 'rgba(245,166,35,0.7)';
    particles.forEach(p=>{
        ctx.beginPath();
        ctx.arc(p.x,p.y,p.r,0,2*Math.PI);
        ctx.fill();
        p.x += p.vx;
        p.y += p.vy;
        if(p.x<0) p.x=canvas.width;
        if(p.x>canvas.width) p.x=0;
        if(p.y<0) p.y=canvas.height;
        if(p.y>canvas.height) p.y=0;
    });
    requestAnimationFrame(drawParticles);
}
window.addEventListener('resize', initParticles);
initParticles();
drawParticles();

// marquee pause on hover
const marquee = document.querySelector('.marquee-content');
marquee.addEventListener('mouseenter', ()=>{ marquee.style.animationPlayState='paused'; });
marquee.addEventListener('mouseleave', ()=>{ marquee.style.animationPlayState='running'; });

// simple drag scroll for carousel
const carousel = document.getElementById('news-carousel');
let isDown = false, startX, scrollLeft;
if(carousel){
    carousel.addEventListener('mousedown',(e)=>{
        isDown=true;
        startX=e.pageX- carousel.offsetLeft;
        scrollLeft=carousel.scrollLeft;
    });
    carousel.addEventListener('mouseleave',()=>{isDown=false;});
    carousel.addEventListener('mouseup',()=>{isDown=false;});
    carousel.addEventListener('mousemove',(e)=>{
        if(!isDown) return;
        e.preventDefault();
        const x = e.pageX - carousel.offsetLeft;
        const walk = (x-startX)*2;
        carousel.scrollLeft = scrollLeft - walk;
    });
}

// shimmer text effect
function addShimmer(){
    document.querySelectorAll('.section-title, .hero-title').forEach(el=>{
        el.classList.add('shimmer');
    });
}
addShimmer();

// page transition fade out
const links = document.querySelectorAll('a[href]');
links.forEach(link=>{
    if(link.target||link.href.startsWith('#')) return;
    link.addEventListener('click',(e)=>{
        e.preventDefault();
        document.body.classList.remove('loaded');
        setTimeout(()=>{ window.location = link.href; },300);
    });
});
