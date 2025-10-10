
 // *********** intro section animation **********
    document.addEventListener("DOMContentLoaded", function () {
      const lines = [
        "Create invoices with just your voice",
        "Fast, smart, and professional"
      ];

      const speed = 60; // typing speed
      let lineIndex = 0;
      let charIndex = 0;

      function typeWriter() {
        if (lineIndex < lines.length) {
          const currentLine = lines[lineIndex];
          if (charIndex < currentLine.length) {
            document.getElementById("line" + (lineIndex + 1)).textContent += currentLine.charAt(charIndex);
            charIndex++;
            setTimeout(typeWriter, speed);
          } else {
            //  finished class for pipe after line completes
            document.getElementById("line" + (lineIndex + 1)).classList.add("finished");
            lineIndex++;
            charIndex = 0;
            setTimeout(typeWriter, 600); // pause before next line
          }
        }
      }

      typeWriter();
    });


    // ******* Typographic cluster small parallax handler (subtle depth)  ********
    (function () {
      const cluster = document.getElementById('typoCluster');
      if (!cluster) return;
      const words = cluster.querySelectorAll('.word');
      const maxOffset = 18; // px max shift

      const reset = () => words.forEach(w => { w.style.setProperty('--tx', '0px'); w.style.setProperty('--ty', '0px'); });

      cluster.addEventListener('mousemove', (e) => {
        const rect = cluster.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const nx = (e.clientX - cx) / (rect.width / 2);
        const ny = (e.clientY - cy) / (rect.height / 2);

        words.forEach((w, i) => {
          const depth = (i % 2 === 0 ? 1 : -1) * (6 + i * 4);
          const tx = (nx * depth * maxOffset / 20).toFixed(2) + 'px';
          const ty = (ny * depth * maxOffset / 20).toFixed(2) + 'px';
          w.style.setProperty('--tx', tx);
          w.style.setProperty('--ty', ty);
        });
      });

      cluster.addEventListener('mouseleave', () => {
        words.forEach(w => { w.style.transition = 'transform .6s cubic-bezier(.2,.9,.2,1)'; });
        reset();
        setTimeout(() => words.forEach(w => w.style.transition = ''), 650);
      });
    })();


//  **** clerk authentication ********
window.addEventListener("load", async () => {
    await Clerk.load();

    const authButtons = document.getElementById("auth-buttons");

    if (Clerk.user) {
      // If logged in -> Show profile + sign out
      authButtons.innerHTML = `
        <div class="dropdown">
          <a class="btn btn-outline-light dropdown-toggle d-flex align-items-center" href="#" role="button" data-bs-toggle="dropdown">
            <img src="${Clerk.user.imageUrl}" class="rounded-circle me-2" width="28" height="28"> 
            ${Clerk.user.firstName || "Profile"}
          </a>
          <ul class="dropdown-menu dropdown-menu-end">
            <li><a class="dropdown-item" href="#" onclick="Clerk.openUserProfile()">Profile Settings</a></li>
            <li><a class="dropdown-item" href="#" onclick="Clerk.signOut()">Sign Out</a></li>
          </ul>
        </div>
      `;
    } else {
      // If not logged in -> Show Sign In / Sign Up with redirection to index page after authentication.
      authButtons.innerHTML = `
        <a class="btn btn-outline-secondary" onclick="Clerk.openSignIn({ afterSignInUrl: '/' })">Sign In</a>
        <a class="btn btn-success ms-1" onclick="Clerk.openSignUp({ afterSignUpUrl: '/' })">Sign Up</a>
      `;
    }
});


    // ****** call Flask protected route with session token *******
    async function callProtected() {
  if (!Clerk.session) {
    alert("You must be logged in!");
    return;
  }

  const token = await Clerk.session.getToken({ template: "default" });

  const res = await fetch("/protected", {
    headers: {
      "Authorization": "Bearer " + token
    }
  });

  const data = await res.json();
  console.log(data);
}


// make the nav item ative 
document.addEventListener("DOMContentLoaded", function () {
    const navLinks = document.querySelectorAll(".nav-link, .get-started-btn");

    function setActive(link) {
      navLinks.forEach(l => l.classList.remove("active"));
      link.classList.add("active");
    }

    // On page load → match current route
    const currentPath = window.location.pathname;
    navLinks.forEach(link => {
      const href = link.getAttribute("href");

      // Match normal Flask routes
      if (href && href !== "javascript:void(0)" && href === currentPath) {
        setActive(link);
      }

      // invoice_tool route → highlight Generate Invoice
      if (currentPath === "/invoice_tool" && link.textContent.trim() === "Generate Invoice") {
        setActive(link);
      }
    });

    // On click (JS-only links like Get Started)
    navLinks.forEach(link => {
      link.addEventListener("click", function (e) {
        if (this.getAttribute("href") === "javascript:void(0)") {
          e.preventDefault();
        }
        setActive(this);
      });
    });
  });

//  *********** go to tool page  ********

  // Clerk init
  window.Clerk.load().then(() => {
    console.log("Clerk loaded");
  });

  async function goToTool() {
    const user = window.Clerk.user;

    if (user) {
      // User is signed in
      window.location.href = "/invoice_tool";  
    } else {
      // Not signed in → open Clerk signup
      window.Clerk.openSignUp();
    }
  }


  
  // Contact page
document.addEventListener("DOMContentLoaded", function () {
  const contactFormContainer = document.querySelector(".contact-form");
  const originalContactFormHTML = contactFormContainer
    ? contactFormContainer.innerHTML
    : "";

  function attachContactFormHandler() {
    const contactForm = document.querySelector(".contact-form form");
    if (contactForm) {
      contactForm.addEventListener(
        "submit",
        function (e) {
          e.preventDefault();

          // Disable the submit button + show spinner
          const submitButton = contactForm.querySelector("button[type='submit']");
          if (submitButton) {
            submitButton.disabled = true;
            submitButton.innerHTML =
              '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Sending...';
          }

          // Gather form data
          const formData = new FormData(contactForm);
          const dataObj = {
            name: formData.get("name"),
            email: formData.get("email"),
            subject: formData.get("subject"),
            message: formData.get("message"),
          };

          // Send request
          fetch("/submit-contact", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(dataObj),
          })
            .then((response) => response.json())
            .then((data) => {
              if (data.error) {
                // Backend returned error JSON
                throw new Error(data.error);
              }

              let feedback =
                data.message ||
                "Thank you for your message! We will respond shortly.";

              // Replace container with success message
              contactFormContainer.innerHTML = `
                <div class="form-submitted">
                  <span class="material-symbols-rounded success-icon">check_circle</span>
                  <h3>Message Sent!</h3>
                  <p>${feedback}</p>
                  <button type="button" class="send-another-btn">Send Another Message</button>
                </div>
              `;

              // Restore form when "Send Another Message" is clicked
              document
                .querySelector(".send-another-btn")
                .addEventListener("click", () => {
                  contactFormContainer.innerHTML = originalContactFormHTML;
                  attachContactFormHandler();
                });
            })
            .catch((error) => {
              console.error("Error submitting contact form:", error);

              contactFormContainer.innerHTML = `
                <div class="form-submitted">
                  <span class="material-symbols-rounded error-icon">error</span>
                  <h3>Error</h3>
                  <p>${
                    error.message ||
                    "There was an error sending your message. Please try again later."
                  }</p>
                  <button type="button" class="send-another-btn">Try Again</button>
                </div>
              `;

              // Retry handler
              document
                .querySelector(".send-another-btn")
                .addEventListener("click", () => {
                  contactFormContainer.innerHTML = originalContactFormHTML;
                  attachContactFormHandler();
                });
            });
        },
        { once: true } // Prevent multiple submits
      );
    }
  }

  if (contactFormContainer) {
    attachContactFormHandler();
  }
});
