$(document).ready(function() {
  $("#wrapper").toggleClass("toggled");
$("#menu-toggle").click(function(e) {
    e.preventDefault();
    $("#wrapper").toggleClass("toggled");
});
});