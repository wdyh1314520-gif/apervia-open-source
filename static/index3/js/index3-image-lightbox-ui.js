/* Image lightbox event binding.*/

(function bindImageLightboxUi(){
  function lightboxIsOpen(){
    return !!imageLightboxEl?.classList?.contains("open");
  }

  imageLightboxCloseEl?.addEventListener("click", (event)=>{
    event.preventDefault();
    event.stopPropagation();
    closeImageLightbox();
  });

  imageLightboxPrevEl?.addEventListener("click", (event)=>{
    event.preventDefault();
    event.stopPropagation();
    stepImageLightbox(-1);
  });

  imageLightboxNextEl?.addEventListener("click", (event)=>{
    event.preventDefault();
    event.stopPropagation();
    stepImageLightbox(1);
  });

  imageLightboxEl?.addEventListener("click", (event)=>{
    if(event.target === imageLightboxEl) closeImageLightbox();
  });

  document.addEventListener("keydown", (event)=>{
    if(!lightboxIsOpen()) return;
    if(event.key === "Escape"){
      event.preventDefault();
      closeImageLightbox();
    }else if(event.key === "ArrowLeft"){
      event.preventDefault();
      stepImageLightbox(-1);
    }else if(event.key === "ArrowRight"){
      event.preventDefault();
      stepImageLightbox(1);
    }
  });
})();
