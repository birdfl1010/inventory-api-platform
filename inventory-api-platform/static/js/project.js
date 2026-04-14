/* Project specific Javascript goes here. */
function clearCheckBoxes(name){
    var clist = document.getElementsByName(name);
    for (var i = 0; i < clist.length; ++i) { clist[i].checked = false; }
  }

  function selectCheckBoxes(name){
    var clist = document.getElementsByName(name);
    for (var i = 0; i < clist.length; ++i) { clist[i].checked = true; }
  }
